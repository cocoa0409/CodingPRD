"""Record construction with common system fields (PRD §2.5).

Common fields: id (UUID), created_at (ISO ms), updated_at (ISO ms), version
(int starting at 1, incremented on every mutation).

TestDayRecord is the exception: immutable append-only, carries only id and
created_at (no updated_at, no version) — PRD §2.5.
"""
import db
from util import new_id, iso_now_ms


def make_record(fields, common=True):
    """Create a record dict with system fields and a monotonic _seq."""
    rec = dict(fields)
    rec["id"] = new_id()
    rec["created_at"] = iso_now_ms()
    rec["_seq"] = db.next_seq()
    if common:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(rec):
    """Refresh updated_at and increment version on a mutation (PRD §2.5/§2.8)."""
    rec["updated_at"] = iso_now_ms()
    rec["version"] = rec.get("version", 0) + 1
    return rec
