"""Record lifecycle: creation stamps, mutation touch (PRD 2.5, 2.11)."""
from db import db, next_seq
from util import CLOCK, new_id


def new_record(collection, fields, versioned=True):
    rec = dict(fields)
    rec["id"] = new_id()
    ts = CLOCK.now_iso()
    rec["created_at"] = ts
    if versioned:
        rec["updated_at"] = ts
        rec["version"] = 1
    rec["_seq"] = next_seq()
    db[collection][rec["id"]] = rec
    return rec


def touch(rec):
    """Every mutation of a resource refreshes updated_at and increments version."""
    rec["updated_at"] = CLOCK.now_iso()
    rec["version"] = rec.get("version", 1) + 1
