"""In-memory data store + logical clock. Starts empty on every boot; no seeding."""
import uuid
from datetime import datetime, timezone, timedelta

# --- Logical clock (PRD 2.4): startup default exactly 2026-08-01T00:00:00Z ---
_clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def get_clock():
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt


def new_id():
    return str(uuid.uuid4())


# --- Wall-clock timestamps for created_at/updated_at (monotonic, unique) ---
_last_wall = None


def wall_now():
    global _last_wall
    n = datetime.now(timezone.utc)
    if _last_wall is not None and n <= _last_wall:
        n = _last_wall + timedelta(milliseconds=1)
    _last_wall = n
    return n


def fmt_ts3(dt):
    """ISO 8601 UTC with exactly three fractional digits (created_at/updated_at)."""
    if dt is None:
        return None
    d = dt.astimezone(timezone.utc)
    return d.strftime('%Y-%m-%dT%H:%M:%S.') + f"{d.microsecond // 1000:03d}Z"


def fmt_instant(dt):
    """Logical-clock instants: no fractional part when zero (matches '2026-08-01T00:00:00Z')."""
    if dt is None:
        return None
    d = dt.astimezone(timezone.utc)
    if d.microsecond == 0:
        return d.strftime('%Y-%m-%dT%H:%M:%SZ')
    if d.microsecond % 1000 == 0:
        return d.strftime('%Y-%m-%dT%H:%M:%S.') + f"{d.microsecond // 1000:03d}Z"
    return d.strftime('%Y-%m-%dT%H:%M:%S.%fZ')


# --- Stores (dicts keyed by id) ---
households = {}
allowances = {}
allowance_index = {}   # (household_id, calendar_year) -> allowance id
amnesty_windows = {}
route_days = {}
pickup_requests = {}
items = {}
assessments = {}
reports = {}
notifications = {}
