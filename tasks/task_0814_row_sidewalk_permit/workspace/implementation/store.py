import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Logical clock. Startup default is exactly 2026-03-01T00:00:00Z and it holds
# that value until explicitly moved; it never reflects real wall-clock time.
# ---------------------------------------------------------------------------
_clock = {"now": datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)}


def clock_now():
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt.astimezone(timezone.utc)


def clock_iso():
    return iso(_clock["now"])


def clock_date_str():
    return _clock["now"].astimezone(timezone.utc).date().isoformat()


# ---------------------------------------------------------------------------
# In-memory collections. These are module-level dicts and therefore start
# empty on every process boot. Nothing is ever seeded here.
# ---------------------------------------------------------------------------
applicants = {}
street_segments = {}
sidewalk_spans = {}
permits = {}
tcps = {}
bonds = {}
lane_closures = {}
sidewalk_obstructions = {}
encroachment_agreements = {}
violations = {}

_seq = {"n": 0}


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def new_id():
    return str(uuid.uuid4())


def iso(dt):
    """ISO 8601 UTC with exactly three fractional (millisecond) digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return iso(datetime.now(timezone.utc))


def base_fields():
    """Common id/created_at/updated_at/version fields for versioned resources."""
    t = now_iso()
    return {
        "id": new_id(),
        "created_at": t,
        "updated_at": t,
        "version": 1,
        "_seq": next_seq(),
    }


def immutable_base_fields():
    """id/created_at only (for ViolationNotice, which is immutable)."""
    return {"id": new_id(), "created_at": now_iso(), "_seq": next_seq()}


def touch(entity):
    """Refresh updated_at and bump version on any mutation (incl. cascades)."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1


def serialize(entity):
    """Public view of a resource: drop internal (underscore-prefixed) keys."""
    if isinstance(entity, dict):
        return {k: v for k, v in entity.items() if not k.startswith("_")}
    return entity


def sorted_by_created(values):
    return sorted(values, key=lambda e: (e["created_at"], e["_seq"]))
