"""In-memory data store, logical clock, and id/time helpers.

All state is process-local and wiped on every fresh boot (start.sh re-invocation).
No persistence, no seeding.
"""
import uuid
import random
import string
import itertools
from datetime import datetime, timezone, timedelta

UTC = timezone.utc
DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=UTC)

# ---------------------------------------------------------------------------
# Entity collections (dicts keyed by id)
# ---------------------------------------------------------------------------
depots = {}
chargers = {}
vehicles = {}
drivers = {}
charge_sessions = {}
telemetry_readings = {}
work_orders = {}
route_assignments = {}
reimbursement_claims = {}
invoices = {}

# Logical clock -------------------------------------------------------------
_clock = {"now": DEFAULT_CLOCK}
_seq = itertools.count(1)


def now():
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt


def reset():
    """Wipe all state (used only defensively; a fresh process already is empty)."""
    for d in (depots, chargers, vehicles, drivers, charge_sessions,
              telemetry_readings, work_orders, route_assignments,
              reimbursement_claims, invoices):
        d.clear()
    _clock["now"] = DEFAULT_CLOCK


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


# ---------------------------------------------------------------------------
# datetime helpers
# ---------------------------------------------------------------------------
def parse_dt(value):
    """Parse an ISO 8601 datetime string into a UTC-aware datetime, or None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        if not isinstance(value, str):
            raise ValueError("not a datetime string")
        s = value.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def iso_out(dt):
    """Serialize a datetime to ISO 8601 UTC with three fractional digits + Z."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


# Keys whose stored values are datetime objects and must be serialized.
_DT_KEYS = {
    "created_at", "updated_at", "scheduled_start", "scheduled_end",
    "actual_start", "actual_end", "opened_at", "resolved_at",
    "reading_time", "scheduled_departure",
}


def serialize(entity):
    """Return a JSON-ready copy of an entity dict (datetimes -> ISO strings)."""
    out = {}
    for k, v in entity.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = iso_out(v)
        else:
            out[k] = v
    return out
