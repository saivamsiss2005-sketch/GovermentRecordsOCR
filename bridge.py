"""
Bridge script: Invoked by Node.js backend.
Commands:
  process <file1> <file2> ...  -> prints JSON of extracted records
  samples                      -> processes samples and prints JSON
  export-excel <temp_json> <out_path>
"""
import sys
import os
import json
import uuid
import hashlib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OCR_ENGINE_ROOT = PROJECT_ROOT / "ocr_engine"
sys.path.insert(0, str(OCR_ENGINE_ROOT))

from src.pipeline import GovtRecordPipeline
from src.document_parser import ParsedDocument
from src.entity_extractor import ExtractedRecord

pipeline = GovtRecordPipeline()

# ── File-hash result cache ────────────────────────────────────────────────────
# Cache is a JSON file mapping MD5(file_bytes) -> extracted record dict.
# This means: upload the same document again = instant result, zero re-OCR.
CACHE_FILE = PROJECT_ROOT / "backend" / "server" / "ocr_cache.json"
LEGACY_RAW_TEXT_LIMIT = 3000

def _load_cache() -> dict:
    try:
        if CACHE_FILE.exists():
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def _save_cache(cache: dict):
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

def _file_hash(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def _is_cache_entry_reusable(record: dict) -> bool:
    raw_text = record.get("raw_text")
    return isinstance(raw_text, str) and len(raw_text) < LEGACY_RAW_TEXT_LIMIT

def record_to_dict(p_doc: ParsedDocument, e_rec: ExtractedRecord, original_name: str = None):
    return {
        "id": str(uuid.uuid4()),
        "file_name": original_name or Path(p_doc.file_path).name,
        "file_type": p_doc.file_type.upper(),
        "file_size_kb": p_doc.file_size_kb,
        "is_scanned": p_doc.is_scanned,
        "document_type": e_rec.document_type,
        "record_id": e_rec.record_id,
        "person_name": e_rec.person_name,
        "relation_name": e_rec.relation_name,
        "gender": e_rec.gender,
        "dob": e_rec.dob,
        "age": e_rec.age,
        "national_id": e_rec.national_id,
        "address": e_rec.address,
        "village_or_town": e_rec.village_or_town,
        "taluka_or_mandal": e_rec.taluka_or_mandal,
        "district": e_rec.district,
        "state": e_rec.state,
        "pincode": e_rec.pincode,
        "issue_date": e_rec.issue_date,
        "issuing_authority": e_rec.issuing_authority,
        "department": e_rec.department,
        "land_details": e_rec.land_details,
        "financial_details": e_rec.financial_details,
        "status": e_rec.status,
        "confidence": e_rec.extraction_confidence,
        "key_values": e_rec.all_key_values,
        "raw_text": e_rec.raw_text
    }

def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "No command provided"}))
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "process":
        files = sys.argv[2:]
        results = []

        # Load cache once
        cache = _load_cache()
        cache_updated = False

        for f in files:
            p = Path(f)
            if not p.exists():
                continue
            try:
                file_md5 = _file_hash(str(p))
                if file_md5 in cache:
                    # Cache HIT — instant result, no re-OCR
                    cached = cache[file_md5].copy()
                    if _is_cache_entry_reusable(cached):
                        results.append(cached)
                        continue

                # Cache MISS — run full pipeline
                p_doc, e_rec = pipeline.process_file(str(p))
                record = record_to_dict(p_doc, e_rec)
                results.append(record)

                # Store in cache (keyed by content hash, not filename)
                cache[file_md5] = record
                cache_updated = True

            except Exception as e:
                results.append({"file_name": p.name, "error": str(e)})

        if cache_updated:
            _save_cache(cache)

        print(json.dumps(results))

    elif cmd == "samples":
        samples_dir = PROJECT_ROOT / "samples"
        candidates = list(samples_dir.glob("*.pdf")) + list(samples_dir.glob("*.docx"))
        results = []
        for p in candidates:
            try:
                p_doc, e_rec = pipeline.process_file(str(p))
                results.append(record_to_dict(p_doc, e_rec))
            except Exception as e:
                pass
        print(json.dumps(results))

    elif cmd == "export_excel":
        if len(sys.argv) < 4:
            sys.exit(1)
        files_json_path = sys.argv[2]
        output_excel_path = sys.argv[3]
        
        with open(files_json_path, "r", encoding="utf-8") as f:
            file_paths = json.load(f)

        parsed_docs = []
        extracted_recs = []
        for fp in file_paths:
            try:
                p_doc, e_rec = pipeline.process_file(fp)
                parsed_docs.append(p_doc)
                extracted_recs.append(e_rec)
            except Exception:
                pass

        pipeline.exporter.export(
            records=extracted_recs,
            parsed_docs=parsed_docs,
            output_path=output_excel_path
        )
        print(json.dumps({"success": True, "path": output_excel_path}))

if __name__ == "__main__":
    main()
