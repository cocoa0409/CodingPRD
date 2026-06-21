"""Entity record creation, mutation, and serialization of common fields."""
from db import new_id, now_iso, store


def make_record(collection_attr, fields):
    """Create a record with common fields (id, created_at, updated_at, version)
    plus an internal _seq for ordering. Returns the stored dict."""
    rid = new_id()
    ts = now_iso()
    rec = {
        "id": rid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
    }
    rec.update(fields)
    getattr(store, collection_attr)[rid] = rec
    return rec


def touch(rec):
    """Mark a record as mutated: bump version and updated_at."""
    rec["version"] += 1
    rec["updated_at"] = now_iso()


# Fields that are internal-only and must not be serialized to clients.
_HIDDEN = {"_seq"}


def serialize(rec):
    return {k: v for k, v in rec.items() if k not in _HIDDEN}
