"""Common record lifecycle helpers (PRD §2.4).

First-class records carry id, created_at, updated_at, version (starts at 1,
+1 on every mutation). The Holiday resource is the sole exception: it carries
only id and created_at (no updated_at, no version).
"""
import db
from util import new_id, iso_now


def new_record(extra_fields):
    """Build a common-fielded record dict (id, created_at, updated_at, version)."""
    ts = iso_now()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    rec.update(extra_fields)
    return rec


def new_holiday_record(extra_fields):
    """Holiday: id + created_at only (immutable, no version)."""
    rec = {
        "id": new_id(),
        "created_at": iso_now(),
        "_seq": db.next_seq(),
    }
    rec.update(extra_fields)
    return rec


def touch(rec):
    """Mutation bump: refresh updated_at and increment version by exactly one."""
    rec["updated_at"] = iso_now()
    rec["version"] = rec.get("version", 0) + 1


def sort_by_created(records):
    """Default ordering: created_at ascending (insertion seq breaks ties)."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def public(rec, exclude=None):
    """Strip internal-only keys (those prefixed with _) for serialization."""
    exclude = exclude or set()
    return {k: v for k, v in rec.items() if not k.startswith("_") and k not in exclude}
