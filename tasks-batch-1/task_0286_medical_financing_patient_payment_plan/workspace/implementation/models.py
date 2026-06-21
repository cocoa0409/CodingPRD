"""Entity construction, common-field management, and serialization.

Internal representation: plain dicts. Datetime-valued fields are stored as
aware datetimes and serialized to ISO-8601 (3 fractional digits) on output.
Common fields (PRD §2.4): id (UUID, no prefix), created_at, updated_at, version.
"""
import db
from db import iso

# Per-entity datetime fields that must be ISO-serialized in responses.
_DATETIME_FIELDS = {
    "effective_start", "effective_end", "promo_start", "promo_end",
    "posted_at", "period_start", "period_end", "due_date",
}


def new_entity(extra):
    now = db.clock.now()
    ent = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }
    ent.update(extra)
    return ent


def touch(ent):
    """Bump version + refresh updated_at on a mutation (PRD §2.4)."""
    ent["version"] += 1
    ent["updated_at"] = db.clock.now()


def serialize(ent):
    """Project an internal entity dict to its public JSON form."""
    out = {}
    for key, value in ent.items():
        if key.startswith("_"):
            continue
        if key in ("created_at", "updated_at") or key in _DATETIME_FIELDS:
            out[key] = iso(value) if value is not None else None
        else:
            out[key] = value
    return out
