"""In-memory store (section 2.4 identity + section 2.9 version bookkeeping).

Storage is process memory only: plain dicts keyed by id. Nothing is seeded at
import time or at startup - every entity is created by an API call.
"""

import uuid

from flask import g, has_app_context

import clock

COLLECTIONS = (
    "employees",
    "dependents",
    "programs",
    "doc_rules",
    "cases",
    "submissions",
    "amnesty_removals",
    "appeals",
    "notices",
    "recoveries",
    "claim_lines",
    "communications",
)

_data = {name: {} for name in COLLECTIONS}
_counter = {"seq": 0}
_fallback_dirty = []

# collections whose rows carry the full id/created_at/updated_at/version quartet
VERSIONED = frozenset(
    {
        "employees",
        "dependents",
        "programs",
        "doc_rules",
        "cases",
        "submissions",
        "appeals",
        "notices",
        "recoveries",
    }
)


def collection(name):
    return _data[name]


def employees():
    return _data["employees"]


def reset_all():
    for name in COLLECTIONS:
        _data[name].clear()
    _counter["seq"] = 0
    del _fallback_dirty[:]
    clock.reset()


def next_seq():
    _counter["seq"] += 1
    return _counter["seq"]


def new_id():
    return str(uuid.uuid4())


# ------------------------------------------------------------------ records


def insert(collection_name, fields):
    """Create a record. Versioned collections get created_at/updated_at/version."""
    rec = {"id": new_id(), "_seq": next_seq(), "_collection": collection_name}
    stamp = clock.now()
    rec["created_at"] = stamp
    if collection_name in VERSIONED:
        rec["updated_at"] = stamp
        rec["version"] = 1
    rec.update(fields)
    rec["_new"] = True
    _data[collection_name][rec["id"]] = rec
    return rec


def _dirty_set():
    if has_app_context():
        if not hasattr(g, "dirty_records"):
            g.dirty_records = []
        return g.dirty_records
    return _fallback_dirty


def mark_dirty(rec):
    """Flag a record as mutated by this request (version bumps once at commit)."""
    if rec is None or rec.get("_new"):
        return
    bucket = _dirty_set()
    for existing in bucket:
        if existing is rec:
            return
    bucket.append(rec)


_MISSING = object()


def set_fields(rec, **changes):
    """Assign fields, marking the record dirty only when a value really changed."""
    changed = False
    for key, value in changes.items():
        if rec.get(key, _MISSING) != value:
            rec[key] = value
            changed = True
    if changed:
        mark_dirty(rec)
    return changed


def commit():
    """Apply the per-request updated_at refresh and single version increment."""
    bucket = _dirty_set()
    stamp = clock.now()
    for rec in bucket:
        if rec.get("_collection") in VERSIONED:
            rec["updated_at"] = stamp
            rec["version"] = rec.get("version", 1) + 1
    del bucket[:]
    clear_new_flags()


def clear_new_flags():
    for name in COLLECTIONS:
        for rec in _data[name].values():
            if rec.get("_new"):
                rec["_new"] = False


# ------------------------------------------------------------------ lookups


def get(collection_name, rec_id):
    if not isinstance(rec_id, str):
        return None
    return _data[collection_name].get(rec_id)


def ordered(collection_name, predicate=None):
    """All rows in created_at ascending order (insertion order breaks ties)."""
    rows = [
        r for r in _data[collection_name].values() if predicate is None or predicate(r)
    ]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows
