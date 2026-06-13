"""Entity construction, common-field management, and mutation/version bumping.

Every entity carries: id, created_at, updated_at, version (PRD §2.4).
Entities are stored as plain dicts; the stored dict IS the serialized form.
"""
from db import STORE, new_id, now_iso


def base_entity():
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": STORE.next_seq(),
    }


def touch(entity):
    """Record a mutation: refresh updated_at and increment version (PRD §2.4)."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1


def serialize(entity):
    """Public representation: stored dict minus private keys."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def sort_by_created(items):
    """List default sort: creation order ascending (PRD §2.3)."""
    return sorted(items, key=lambda e: e["_seq"])
