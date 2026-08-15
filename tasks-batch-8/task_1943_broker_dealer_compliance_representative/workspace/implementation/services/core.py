"""Record lifecycle helpers: creation, mutation stamping, stable ordering."""
import itertools

from db import db
from util import new_id, stamp

_seq_counter = itertools.count(1)


def new_record(collection, fields):
    """Create a record with common system fields (PRD 2.4). version starts at 1."""
    now = stamp()
    rec = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next(_seq_counter),
    }
    rec.update(fields)
    db[collection][rec["id"]] = rec
    return rec


def touch(rec):
    """Every mutation refreshes updated_at and increments version (PRD 2.4)."""
    rec["updated_at"] = stamp()
    rec["version"] += 1


def public(rec):
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def by_creation(records):
    """Creation-order sort (created_at ASC; _seq is the monotonic tiebreak so
    records created in the same logical instant keep their true creation order)."""
    return sorted(records, key=lambda r: r["_seq"])
