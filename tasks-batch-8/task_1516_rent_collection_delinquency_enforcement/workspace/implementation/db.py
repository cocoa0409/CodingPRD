"""In-memory data store. The store starts EMPTY on every boot — no seeding.

Also owns the logical clock (PRD 2.4): it starts at exactly
2026-08-01T00:00:00Z before any clock-setting call and never falls back to
wall-clock time. All created_at/updated_at stamps and the envelope's
api_request_timestamp derive from the logical clock (with a monotonic
millisecond counter so ordering by created_at is stable within one instant).
"""

import uuid
from datetime import datetime, timezone

# --- entity stores: dicts keyed by id ----------------------------------------
properties = {}
tenants = {}
leases = {}
charges = {}
payments = {}
allocations = {}
notices = {}
plans = {}
disputes = {}
referrals = {}

# Waiver bookkeeping for the property monthly cap (PRD 3.5): one entry per
# waive action — {"property_id", "month" ("YYYY-MM" by logical clock),
# "amount_cents"}.
waiver_events = []


def new_id():
    return str(uuid.uuid4())


# --- logical clock -----------------------------------------------------------
_DEFAULT_RAW = "2026-08-01T00:00:00Z"
_clock = {
    "instant": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc),
    "raw": _DEFAULT_RAW,
}


def clock_instant():
    return _clock["instant"]


def clock_date():
    return _clock["instant"].date()


def clock_raw():
    return _clock["raw"]


def set_clock(instant, raw):
    _clock["instant"] = instant
    _clock["raw"] = raw


def today_str():
    return clock_date().isoformat()


# --- logical-clock-derived monotonic timestamps ------------------------------
_last_ms = -1


def now_ts():
    """ISO 8601 UTC timestamp with three fractional digits, derived from the
    logical clock and strictly increasing across the process so that ordering
    by created_at is stable (PRD 2.3/2.5)."""
    global _last_ms
    base = int(_clock["instant"].timestamp() * 1000)
    ms = base if base > _last_ms else _last_ms + 1
    _last_ms = ms
    sec, milli = divmod(ms, 1000)
    dt = datetime.fromtimestamp(sec, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % milli


def init_common(resource):
    ts = now_ts()
    resource["id"] = new_id()
    resource["created_at"] = ts
    resource["updated_at"] = ts
    resource["version"] = 1
    return resource


def touch(resource):
    """Record a mutation: refresh updated_at and bump version by exactly 1
    (PRD 2.7 universal rule)."""
    resource["updated_at"] = now_ts()
    resource["version"] = resource.get("version", 1) + 1


def init_allocation(resource):
    """PaymentAllocation is append-only: only id and created_at (PRD 2.5)."""
    resource["id"] = new_id()
    resource["created_at"] = now_ts()
    return resource
