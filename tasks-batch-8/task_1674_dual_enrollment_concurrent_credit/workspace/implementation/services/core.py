"""Record lifecycle helpers: creation, mutation bookkeeping, serialization."""
from db import db, next_seq
from util import new_id, now_ts

# Resources that carry only id + created_at (PRD 2.6): no updated_at / version.
LIGHTWEIGHT = {"prerequisites", "placement_records", "payments"}


def new_record(collection, fields):
    """Insert a record, stamping id / created_at (+ updated_at, version unless
    the collection is one of the three lightweight ones)."""
    rec = {"id": new_id()}
    rec.update(fields)
    rec["created_at"] = now_ts()
    if collection not in LIGHTWEIGHT:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    rec["_seq"] = next_seq()
    db[collection][rec["id"]] = rec
    return rec


def touch(rec):
    """A mutation: refresh updated_at and bump version (never on lightweight rows)."""
    rec["updated_at"] = now_ts()
    if "version" in rec:
        rec["version"] = rec.get("version", 1) + 1
    return rec


def public(rec):
    """Strip internal (underscore-prefixed) keys for serialization."""
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def sorted_all(collection):
    """All records sorted by created_at ascending (insertion seq tiebreak)."""
    items = list(db[collection].values())
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return items
