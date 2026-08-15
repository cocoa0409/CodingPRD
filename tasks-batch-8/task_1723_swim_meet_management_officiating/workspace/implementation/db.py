"""In-memory data store. Starts completely empty on every boot — no seeding."""

import uuid
from datetime import datetime, timezone

# One dict per entity, keyed by id. Never pre-populated.
STORE = {
    "meets": {},
    "teams": {},
    "swimmers": {},
    "events": {},
    "entries": {},
    "relay_teams": {},
    "relay_legs": {},
    "lane_assignments": {},
    "results": {},
    "officials": {},
    "official_assignments": {},
    "disqualifications": {},
    "records": {},
}

# Logical clock: server-startup default is exactly 2026-08-01T00:00:00Z and it
# never falls back to wall-clock time.
CLOCK = {"now": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}


def new_id():
    return str(uuid.uuid4())


def wall_now():
    return datetime.now(timezone.utc)


def iso3(dt):
    """ISO 8601 UTC with exactly three fractional digits (for created_at/updated_at/meta)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def iso_logical(dt):
    """Render a logical-clock timestamp; no fractional part when zero."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return iso3(dt)


def parse_dt(value):
    """Parse an ISO 8601 datetime into an aware UTC datetime. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("datetime must be a string")
    t = value.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Validate a strict YYYY-MM-DD date string. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("date must be a string")
    datetime.strptime(value, "%Y-%m-%d")
    if len(value) != 10:
        raise ValueError("date must be YYYY-MM-DD")
    return value
