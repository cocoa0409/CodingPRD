"""Entity record lifecycle: creation with common fields, mutation bookkeeping,
listing with pagination. (PRD §2.4 common properties and versioning.)

Records are plain dicts. Each carries a private "_type" so serialization knows
which view to emit and whether it is the append-only ActivityLog (no
updated_at / version).
"""
from errors import err
from util import new_id
import clock

# Entity types that are append-only and therefore carry neither updated_at nor
# version (PRD §2.4 — the activity-log entry is the single exception).
_APPEND_ONLY = {"ActivityLog"}

# Monotonic creation counter. Because the test clock can be pinned to a fixed
# instant, many records may share an identical created_at; _seq records the true
# insertion order so deterministic ordering (list sorts, tie-breaks) never has
# to fall back to the random id, which the PRD forbids as a tie-break.
_seq_counter = 0


def _next_seq():
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


def create(record_dict, store, type_name):
    """Insert a new record with id, created_at, and (unless append-only)
    updated_at=created_at and version=1."""
    now = clock.now()
    rec = dict(record_dict)
    rec["_type"] = type_name
    rec["id"] = new_id()
    rec["created_at"] = now
    rec["_seq"] = _next_seq()
    if type_name not in _APPEND_ONLY:
        rec["updated_at"] = now
        rec["version"] = 1
    store[rec["id"]] = rec
    return rec


def touch(rec):
    """Refresh updated_at and bump version by one on any mutation (PRD §2.4).

    A no-op for append-only records (they are never mutated).
    """
    if rec["_type"] in _APPEND_ONLY:
        return
    rec["updated_at"] = clock.now()
    rec["version"] = rec.get("version", 1) + 1


def get_or_404(store, rec_id, label="resource"):
    rec = store.get(rec_id)
    if rec is None:
        err("ERR_NOT_FOUND", "%s %s not found" % (label, rec_id))
    return rec


def sort_key(rec):
    """Stable ascending order: created_at, then true insertion order (_seq).
    Never falls back to the random id (PRD forbids id as a tie-break)."""
    return (rec["created_at"], rec["_seq"])


def paginate(items, limit, offset):
    """Sort by created_at ascending (PRD §2.3 default order) then window."""
    ordered = sorted(items, key=sort_key)
    total = len(ordered)
    window = ordered[offset: offset + limit]
    return window, total
