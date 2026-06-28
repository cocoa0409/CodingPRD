"""Logical clock.

PRD §2.4: "The logical clock starts at exactly 2026-04-01T00:00:00Z and reads
that default on every access until it is explicitly set; before any set call it
never falls back to wall-clock time."
"""
from datetime import datetime, timezone

DEFAULT_CLOCK_ISO = "2026-04-01T00:00:00Z"


def _parse_iso(value):
    """Parse an ISO 8601 instant (accepting a trailing Z) into an aware UTC datetime."""
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class LogicalClock:
    def __init__(self):
        self._now = _parse_iso(DEFAULT_CLOCK_ISO)

    def now(self):
        """Return the current logical instant as an aware UTC datetime."""
        return self._now

    def set_iso(self, iso_value):
        self._now = _parse_iso(iso_value)
        return self._now


def iso_millis(dt):
    """Format an aware datetime as ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
