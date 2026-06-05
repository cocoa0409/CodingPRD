"""Entity construction, common-field management, and serialization.

Common fields (PRD §2.4): id (UUID, no prefix), created_at, updated_at (ISO 8601
UTC, 3 fractional digits), version (starts at 1, +1 each mutation). Timestamps use
the logical clock so that created_at/updated_at align with the test-driven clock.
"""
from db import db
from util import new_id, iso_now


def _stamp_now():
    return db.current_utc


def make_entity(extra_fields):
    """Create a base entity dict with common fields plus the given fields."""
    now = _stamp_now()
    ent = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    ent["_seq"] = db.next_seq()
    ent.update(extra_fields)
    return ent


def touch(ent):
    """Refresh updated_at and bump version by exactly 1 (PRD §2.4)."""
    ent["updated_at"] = _stamp_now()
    ent["version"] = ent["version"] + 1


# ---- Serialization ------------------------------------------------------

# Internal bookkeeping keys never emitted in responses.
_INTERNAL = {"_seq"}

# Datetime-typed fields per entity that must be serialized as ISO strings on output.
_DATETIME_FIELDS = {
    "created_at",
    "updated_at",
    "window_start",
    "window_end",
    "start_date",
    "end_date",
    "check_in",
    "check_out",
    "last_synced_at",
    "release_after",
}


def serialize(ent):
    out = {}
    for k, v in ent.items():
        if k in _INTERNAL:
            continue
        if k in _DATETIME_FIELDS:
            out[k] = iso_now(v) if v is not None else None
        else:
            out[k] = v
    return out
