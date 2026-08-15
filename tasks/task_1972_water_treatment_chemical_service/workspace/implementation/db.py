"""In-memory store, logical clock, id/timestamp helpers.

Storage is process-local dicts keyed by id. The store starts EMPTY on every
boot -- no seeding. The logical clock starts at exactly 2026-08-01T00:00:00Z
and never falls back to wall-clock time for business behavior.
"""

import itertools
import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

_INITIAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_clock = {"now": _INITIAL_CLOCK}


def now():
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt
    return _clock["now"]


# ---------------------------------------------------------------------------
# Entity stores (all empty at boot)
# ---------------------------------------------------------------------------

db = {
    "accounts": {},
    "assets": {},
    "program_designs": {},
    "products": {},
    "feed_stations": {},
    "telemetry_readings": {},
    "test_routes": {},
    "route_stops": {},
    "water_test_results": {},
    "corrective_actions": {},
    "coupon_racks": {},
    "corrosion_coupons": {},
    "legionella_plans": {},
    "blowdown_events": {},
    "delivery_orders": {},
    "invoices": {},
}

# Global monotonic insertion sequence for deterministic tie-breaking.
_seq_counter = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq_counter)


# ---------------------------------------------------------------------------
# Timestamp formatting / parsing
# ---------------------------------------------------------------------------

def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2025-05-24T10:30:00.123Z."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_ts_seconds(dt):
    """ISO 8601 UTC whole seconds (computed timestamps like projected_depletion_at)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_clock(dt):
    """Clock echo format: whole seconds unless sub-second precision was supplied."""
    if dt.microsecond:
        return fmt_ts(dt)
    return fmt_ts_seconds(dt)


def parse_iso(value):
    """Parse an ISO 8601 string to an aware UTC datetime. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if not text:
        raise ValueError("empty")
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Entity lifecycle helpers
# ---------------------------------------------------------------------------

def create_entity(kind, fields, common=True):
    """Insert a new entity. Returns the stored dict."""
    ent = dict(fields)
    ent["id"] = new_id()
    ent["created_at"] = now()
    if common:
        ent["updated_at"] = ent["created_at"]
        ent["version"] = 1
    ent["_seq"] = next_seq()
    db[kind][ent["id"]] = ent
    return ent


def touch(ent):
    """Refresh updated_at and increment version (OCC field)."""
    ent["updated_at"] = now()
    ent["version"] += 1
