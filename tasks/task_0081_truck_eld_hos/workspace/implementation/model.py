"""Shared record helpers: system field stamping (PRD §2.4)."""
import db
import clock
import timeutil


def stamp_new(record, common_fields=True):
    """Attach id/created_at and (when common_fields) updated_at/version=1."""
    now = clock.now()
    record["id"] = db.new_id()
    record["created_at"] = timeutil.iso_now_str(now)
    record["_seq"] = db.next_seq()
    if common_fields:
        record["updated_at"] = record["created_at"]
        record["version"] = 1
    return record


def touch(record):
    """Mark a mutation: refresh updated_at and bump version by one (PRD §2.4)."""
    record["updated_at"] = timeutil.iso_now_str(clock.now())
    record["version"] = record.get("version", 0) + 1
