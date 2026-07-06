"""In-memory data store and logical clock.

All state lives in module-level dicts keyed by id. The store starts EMPTY on
every boot — nothing is seeded, preloaded, or hardcoded. Each start.sh
re-invocation produces a fresh process, so all state is wiped automatically.
"""
import uuid
from datetime import datetime, timezone, timedelta

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.5). At server startup the clock holds exactly
# 2026-03-01T00:00:00Z, and before any clock-setting call it reads exactly this
# default and never falls back to real wall-clock time.
# ---------------------------------------------------------------------------
DEFAULT_CLOCK = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": DEFAULT_CLOCK}

# Standard constants (PRD §3.3, §3.8).
WAIVER_VALID_DAYS = 14
SHIFT_REST_MINUTES = 30


def now():
    """Return the current logical clock instant (UTC, tz-aware)."""
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt


# ---------------------------------------------------------------------------
# Entity tables — one dict per entity, keyed by id.
# ---------------------------------------------------------------------------
venues = {}
attractions = {}
time_slots = {}
pricing_rules = {}
guests = {}
waivers = {}
reservations = {}
tickets = {}
pass_products = {}
passes = {}
scare_zones = {}
actor_shifts = {}
closures = {}


def new_id():
    """Server-minted UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def iso(dt):
    """Render a datetime as ISO 8601 UTC with three fractional digits, Z suffix."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value):
    """Parse an ISO 8601 datetime string into a tz-aware UTC datetime.

    Returns None if the value cannot be parsed.
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_days(dt, days):
    return dt + timedelta(days=days)


def add_minutes(dt, minutes):
    return dt + timedelta(minutes=minutes)
