"""Common-field stamping helpers (PRD §2.4, §2.11)."""
import db


def stamp_new(record: dict) -> dict:
    """Set id/created_at/updated_at/version=1 on a fresh record (PRD §2.4)."""
    if "id" not in record:
        record["id"] = db.new_id()
    record["created_at"] = db.now_iso()
    record["updated_at"] = record["created_at"]
    record["version"] = 1
    return record


def touch(record: dict) -> dict:
    """Bump updated_at + version on every mutation (PRD §2.4, §2.11).

    Cascade-touched children get their own bump independently.
    """
    record["updated_at"] = db.now_iso()
    record["version"] = int(record.get("version", 0)) + 1
    return record
