"""Logical clock + UTC instant helpers (PRD §2.8).

Timestamps are stored and compared as UTC instants to millisecond precision,
serialized as ISO 8601 with exactly three fractional digits and a 'Z' suffix.
"""
from datetime import datetime, timezone, timedelta


def now_iso():
    """Wall-clock UTC instant (used for created_at/updated_at and meta timestamp)."""
    return fmt(datetime.now(timezone.utc))


def fmt(dt):
    """Format a datetime as ISO 8601 UTC with three fractional digits + 'Z'."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    # millisecond precision, three digits
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def parse_iso(s):
    """Parse an ISO 8601 instant into a timezone-aware UTC datetime. Raises ValueError on failure."""
    if not isinstance(s, str):
        raise ValueError("not a string instant")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class Clock:
    """Single logical clock for the system (PRD §2.8)."""

    def __init__(self):
        # Default to current wall-clock UTC until a SystemAdmin sets it.
        self._now = datetime.now(timezone.utc)

    def now(self):
        return self._now

    def now_iso(self):
        return fmt(self._now)

    def set_to(self, dt):
        self._now = dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        return self._now

    def advance_hours(self, hours):
        self._now = self._now + timedelta(hours=hours)
        return self._now
