"""Record lifecycle helpers: common fields, mutation bumps, serialization.

Common fields (PRD §2.4): every entity carries id (UUID, no prefix), created_at
(ISO 8601 UTC, 3 fractional digits), updated_at, and version. version begins at
its initial value on creation and increments by exactly one on every mutation.
"""
from db import db, new_id, now_iso

# version begins at 1 on creation (initial value), +1 per mutation.
INITIAL_VERSION = 1


def make_record(table_name, fields):
    """Create a record dict with common fields populated and store it."""
    rid = new_id()
    ts = now_iso()
    rec = {
        "id": rid,
        "created_at": ts,
        "updated_at": ts,
        "version": INITIAL_VERSION,
        "_seq": db.next_seq(),
    }
    rec.update(fields)
    getattr(db, table_name)[rid] = rec
    return rec


def touch(rec):
    """Apply one mutation: refresh updated_at and increment version by one."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec["version"] + 1
    return rec


def public_view(rec):
    """Strip internal-only keys (those prefixed with '_') for the response."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def sort_by_created(rows):
    """Stable ascending sort by created_at, tie-broken by insertion sequence."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
