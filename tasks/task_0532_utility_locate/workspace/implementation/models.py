"""Entity constructors and serialization. Uses a monotonic seq for stable
created_at ordering (creation-timestamp ascending sort)."""
from util import new_id, iso_ms, iso_sec
from db import db

FACILITY_TYPES = {"GAS", "ELECTRIC", "WATER", "SEWER", "TELECOM", "OIL"}
HIGH_PRIORITY_TYPES = {"GAS", "OIL"}


def _base(with_version=True):
    rec = {
        "id": new_id(),
        "created_at": db.clock.get(),
        "_seq": db.next_seq(),
    }
    if with_version:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(rec):
    """Refresh updated_at and bump version on a mutation."""
    if "version" in rec:
        rec["updated_at"] = db.clock.get()
        rec["version"] += 1


# ---------------------------------------------------------------------------
# Serializers — emit datetimes as ISO ms strings; hide internal _seq.
# ---------------------------------------------------------------------------
# Server-managed audit timestamps — three fractional digits (PRD §2.4).
_MS_DT_FIELDS = {"created_at", "updated_at"}
# Computed instants — second granularity, no fractional digits (PRD §2.9).
_SEC_DT_FIELDS = {
    "sla_due_at", "dig_window_opens_at", "dig_window_expires_at",
    "markout_completed_at", "due_at", "responded_at", "dispatched_at",
    "sla_deadline_at", "completed_at", "valid_until",
}


def serialize(rec):
    out = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        if k in _MS_DT_FIELDS:
            out[k] = iso_ms(v) if v is not None else None
        elif k in _SEC_DT_FIELDS:
            out[k] = iso_sec(v) if v is not None else None
        else:
            out[k] = v
    return out
