"""Entity construction, common-field stamping, and serialization.

Common fields (PRD §2.4): every entity carries id / created_at / updated_at /
version EXCEPT ApyTier, which carries only id / created_at (written once, never
mutated). `version` starts at 1 and increments by one on every mutation.
"""
from db import db, new_id, now_iso


def stamp_new(entity, with_version=True):
    """Attach common system fields to a freshly created entity."""
    entity["id"] = new_id()
    ts = now_iso()
    entity["created_at"] = ts
    entity["_seq"] = db.next_seq()  # stable tie-break ordering (private)
    if with_version:
        entity["updated_at"] = ts
        entity["version"] = 1
    return entity


def touch(entity):
    """Refresh updated_at and bump version on mutation (PRD §2.4, §2.7)."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1
    return entity


# Fields that are internal bookkeeping and must never be serialized.
_PRIVATE = {"_seq"}


def public(entity):
    """Return a shallow copy with private bookkeeping fields removed."""
    return {k: v for k, v in entity.items() if k not in _PRIVATE}
