"""Logical clock (PRD §3.8). Server-wide, starts at 2026-05-01T00:00:00Z,
advanced only via POST /_clock/set_current_utc. Never falls back to wall-clock
time. Governs the rolling 24h limit window and stamps created_at/updated_at."""
from datetime import datetime, timedelta, timezone

DEFAULT_NOW = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


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


def add_hours(dt, hours):
    return dt + timedelta(hours=hours)
