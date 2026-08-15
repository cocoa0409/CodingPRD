"""Record lifecycle: creation, mutation stamping, serialization (PRD 2.4)."""
from db import db, next_seq
from util import new_id, now_ts


def new_record(collection, fields):
    rec = dict(fields)
    rec["id"] = new_id()
    ts = now_ts()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = next_seq()
    db[collection][rec["id"]] = rec
    return rec


def touch(rec):
    """Every mutation refreshes updated_at and increments version (PRD 2.4)."""
    rec["updated_at"] = now_ts()
    rec["version"] = rec.get("version", 1) + 1


def public(rec):
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if not k.startswith("_")}
