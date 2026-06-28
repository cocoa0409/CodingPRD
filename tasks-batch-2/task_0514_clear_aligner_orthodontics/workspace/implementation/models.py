"""Entity record factories and common-field management.

Common fields (PRD §2.4): every persisted resource carries `id` (UUID, no
prefix) and `created_at` (ISO 8601 UTC, 3 fractional digits). Most also carry
`updated_at` and an integer `version` starting at 1, incremented on every
mutation. ProgressCheckin is the single exception: it carries only id and
created_at (append-only audit record).
"""
from clock import clock, format_iso8601_ms
from db import db, new_id


def _now_iso():
    return format_iso8601_ms(clock.now())


def base_record(common_fields=True):
    """Create a record skeleton with id + created_at (+ updated_at/version when
    common_fields is True). Also stamps an internal _seq for ordering."""
    rec = {
        "id": new_id(),
        "created_at": _now_iso(),
        "_seq": db.next_seq(),
    }
    if common_fields:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(rec):
    """Refresh updated_at and bump version on a mutation (PRD §2.4 / §2.8).

    No-op for records without versioning (ProgressCheckin)."""
    if "version" in rec:
        rec["version"] += 1
        rec["updated_at"] = _now_iso()


# Fields that are internal bookkeeping and must never be serialized out.
_INTERNAL_FIELDS = {"_seq", "_shipped_by"}


def serialize(rec):
    """Return a JSON-safe copy of a record stripped of internal fields."""
    return {k: v for k, v in rec.items() if k not in _INTERNAL_FIELDS}
