"""Common entity lifecycle helpers: id/created_at/updated_at/version (PRD §2.4)."""

from db import db


def stamp_new(record):
    """Populate common fields on a freshly created entity. version starts at 1."""
    now = db.now_iso()
    record["id"] = db.new_id()
    record["created_at"] = now
    record["updated_at"] = now
    record["version"] = 1
    return record


def touch(record):
    """Register a mutation: refresh updated_at and bump version by one."""
    record["updated_at"] = db.now_iso()
    record["version"] = record.get("version", 0) + 1
    return record
