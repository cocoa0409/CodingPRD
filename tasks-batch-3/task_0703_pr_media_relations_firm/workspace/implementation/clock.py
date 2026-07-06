"""Logical clock.

Per PRD 2.4: the server boots with its clock set to 2026-03-01T00:00:00Z.
Before any explicit set, the clock reads exactly that default instant and never
falls back to real time. A PlatformAdmin may advance or rewind the clock.

All stamped timestamps (sent_at, released_at, delivered_at) and all temporal
preconditions (embargo windows, interview start/end checks) read from this clock.
"""
from datetime import datetime, timezone

DEFAULT_CLOCK_ISO = "2026-03-01T00:00:00Z"


def _parse_iso(s):
    """Parse an ISO-8601 UTC instant into an aware datetime."""
    if not isinstance(s, str):
        raise ValueError("timestamp must be a string")
    raw = s.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class LogicalClock:
    def __init__(self):
        self._now = _parse_iso(DEFAULT_CLOCK_ISO)

    def now(self):
        """Current logical clock as an aware UTC datetime."""
        return self._now

    def set(self, iso_str):
        self._now = _parse_iso(iso_str)

    def now_iso(self):
        """Current logical clock as an ISO-8601 UTC string with 3 fractional digits."""
        return format_iso(self._now)


def format_iso(dt):
    """Format an aware datetime as ISO-8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


clock = LogicalClock()
