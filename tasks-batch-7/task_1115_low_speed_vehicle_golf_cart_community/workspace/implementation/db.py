"""In-memory data store. Empty on every boot. Never seeded."""
import uuid
from datetime import datetime, timezone, timedelta


# ---------------------------------------------------------------------------
# Logical clock: starts at exactly 2026-05-01T00:00:00Z, advanced only via
# POST /_clock/set_current_utc. Never the wall clock.
# ---------------------------------------------------------------------------
_initial_clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock_now = _initial_clock


def now():
    """Current logical-clock instant (timezone-aware UTC)."""
    return _clock_now


def set_clock(to_dt):
    global _clock_now
    _clock_now = to_dt


def iso_now():
    return format_ts(now())


def format_ts(dt):
    """ISO 8601 UTC with exactly 3 fractional digits, trailing Z."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


def parse_ts(s):
    """Parse an ISO 8601 datetime string to an aware UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(s):
    """Parse an ISO 8601 date (YYYY-MM-DD) to a date object."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    parts = s.strip().split("-")
    if len(parts) != 3:
        raise ValueError("bad date")
    y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
    from datetime import date
    return date(y, m, d)


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Stores: plain dicts keyed by id. Created empty; nothing preloaded.
# ---------------------------------------------------------------------------
communities = {}
permit_holders = {}
vehicles = {}
registrations = {}
inspections = {}
insurance_policies = {}
routes = {}
route_passes = {}
charging_stations = {}
charging_reservations = {}
fleet_vehicles = {}
fleet_dispatches = {}
violations = {}


def touch(entity):
    """Refresh updated_at and bump version on any mutation (incl. cascades)."""
    entity["updated_at"] = iso_now()
    entity["version"] = entity.get("version", 1) + 1
