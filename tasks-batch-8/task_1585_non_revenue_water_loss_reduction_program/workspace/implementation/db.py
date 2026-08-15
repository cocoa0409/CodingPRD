"""In-memory data store, logical clock, id/timestamp helpers.

Storage is in-memory only (plain dicts keyed by id). The store starts empty on
every boot; nothing is seeded. The logical clock starts at exactly
2026-08-01T00:00:00Z and never falls back to wall-clock time.
"""

import threading
import uuid
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

store = {
    "dmas": {},
    "water_balance_periods": {},
    "night_flow_assessments": {},
    "leak_surveys": {},
    "leaks": {},
    "customer_meters": {},
    "meter_accuracy_tests": {},
    "unauthorized_consumption_cases": {},
    "pressure_projects": {},
    "intervention_proposals": {},
    "benchmark_reports": {},
    "audit_events": {},
}
audit_order = []  # audit event ids in append order

_seq = [0]
_lock = threading.Lock()


def next_seq():
    with _lock:
        _seq[0] += 1
        return _seq[0]


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

LOGICAL_CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_logical = {"now": LOGICAL_CLOCK_START}


def logical_now():
    return _logical["now"]


def set_logical_now(dt):
    _logical["now"] = dt


# ---------------------------------------------------------------------------
# Timestamps (wall clock, strictly monotonic, 3 fractional digits, UTC)
# ---------------------------------------------------------------------------

_last_ts = {"t": None}


def fmt_dt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def iso_now():
    with _lock:
        t = datetime.now(timezone.utc)
        t = t.replace(microsecond=(t.microsecond // 1000) * 1000)
        if _last_ts["t"] is not None and t <= _last_ts["t"]:
            t = _last_ts["t"] + timedelta(milliseconds=1)
        _last_ts["t"] = t
        return fmt_dt(t)


def parse_dt(value):
    """Parse an ISO 8601 string to an aware UTC datetime; None on failure."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Record helpers
# ---------------------------------------------------------------------------

def new_record():
    ts = iso_now()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(rec):
    """Refresh updated_at and increment version by one (one modification)."""
    rec["updated_at"] = iso_now()
    rec["version"] += 1


def serialize(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def serialize_audit(ev):
    return {k: v for k, v in ev.items() if not k.startswith("_")}


def append_audit(entity_type, entity_id, action, actor_user_id, actor_role, detail):
    ev = {
        "id": new_id(),
        "created_at": iso_now(),
        "entity_type": entity_type,
        "entity_id": entity_id,
        "action": action,
        "actor_user_id": actor_user_id,
        "actor_role": actor_role,
        "detail": detail,
    }
    store["audit_events"][ev["id"]] = ev
    audit_order.append(ev["id"])
    return ev
