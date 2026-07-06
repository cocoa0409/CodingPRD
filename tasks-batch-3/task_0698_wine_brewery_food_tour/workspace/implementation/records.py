"""Record lifecycle helpers (PRD §2.4).

A new primary resource carries id, created_at, updated_at, version. version
"starts at its initial value on creation" — taken here as 1 — and increments by
one on every mutation. created_at is fixed; updated_at refreshes on every
mutation.
"""
from util import new_id, now_iso
from db import db

INITIAL_VERSION = 1


def new_record(extra):
    ts = now_iso()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": INITIAL_VERSION,
        "_seq": db.next_seq(),
    }
    rec.update(extra)
    return rec


def touch(rec):
    """Mutation: bump version by one and refresh updated_at (PRD §2.4)."""
    rec["version"] += 1
    rec["updated_at"] = now_iso()
