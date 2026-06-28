"""Logical clock (PRD §2.4). Server-wide, starts at 2026-01-01T00:00:00Z,
advanced only via POST /_clock/set_current_utc. Never falls back to wall-clock
time. The recording_date of every RecordingOffice tracks this value."""
from datetime import datetime, timezone

DEFAULT_NOW = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self._now = DEFAULT_NOW

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


clock = Clock()


def iso(dt):
    """ISO 8601 UTC with three fractional digits, Z suffix."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def parse_iso(s):
    """Parse an ISO 8601 datetime string into a tz-aware UTC datetime.
    Raises ValueError on malformed input."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    raw = s.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_years(dt, years):
    """Add a number of calendar years to a datetime (leap-day safe)."""
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:
        # Feb 29 -> Feb 28 on a non-leap target year
        return dt.replace(year=dt.year + years, day=28)
