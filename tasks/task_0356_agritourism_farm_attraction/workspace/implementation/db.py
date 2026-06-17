"""In-memory data store. Everything lives in module-level dicts keyed by id.

NO seeding: the store starts empty on every boot. Tests build all state via the API.
"""
import uuid
from datetime import datetime, timezone

# One dict per entity type, keyed by id.
farms = {}
weather_events = {}
pricing_policies = {}
admission_windows = {}
visitors = {}
season_passes = {}
reservations = {}
activity_passes = {}
waivers = {}
pumpkin_purchases = {}
concession_orders = {}
group_bookings = {}

# Test-driving logical clock (PRD §3.8). None => use real wall clock.
_clock_override = None

# Monotonic counter so created_at ties break deterministically by insertion order.
_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq


def new_id():
    return str(uuid.uuid4())


def now():
    """Current server UTC datetime (test-overridable per PRD §3.8)."""
    if _clock_override is not None:
        return _clock_override
    return datetime.now(timezone.utc)


def set_clock(dt):
    global _clock_override
    _clock_override = dt


def iso_now():
    """ISO 8601 UTC with three fractional digits — used for created_at/updated_at."""
    dt = now()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
