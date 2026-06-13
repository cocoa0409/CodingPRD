"""Entity construction + common-field management (PRD §2.4).

Every entity carries the full common set: id, created_at, updated_at, version.
version begins at 1 on create and increments by exactly 1 on every mutation that
changes persisted state; updated_at is refreshed to the time of that mutation.
"""
from db import DB


def stamp_create(record):
    """Set common fields on a freshly created entity."""
    now = DB.iso_millis(DB.now())
    record.setdefault("id", DB.new_id())
    record["created_at"] = now
    record["updated_at"] = now
    record["version"] = 1
    return record


def touch(record):
    """Record a mutation: bump version, refresh updated_at."""
    record["version"] = record.get("version", 1) + 1
    record["updated_at"] = DB.iso_millis(DB.now())
    return record
