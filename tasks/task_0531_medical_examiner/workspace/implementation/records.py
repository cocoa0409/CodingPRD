"""Record creation, common-field management (id/created_at/updated_at/version),
and public serialization (stripping internal `_seq`).

Every entity carries id, created_at, updated_at, version starting at 1 (PRD §2.4).
"""
from db import db


def make_record(fields):
    """Create a record with common fields stamped from the logical clock."""
    now = db.clock.now_iso()
    rec = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }
    rec.update(fields)
    return rec


def touch(rec):
    """Register a mutation: bump version and refresh updated_at."""
    rec["version"] += 1
    rec["updated_at"] = db.clock.now_iso()


def public(rec):
    """Project a record for output, hiding internal fields."""
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if not k.startswith("_")}
