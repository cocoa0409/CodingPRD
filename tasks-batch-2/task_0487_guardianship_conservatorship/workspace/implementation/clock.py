"""Logical clock (PRD §2.10).

The server keeps a logical clock rather than reading wall-clock time. Before any
clock-setting call the clock reads exactly 2026-01-01T00:00:00Z (startup default)
and never falls back to real time.
"""

from datetime import datetime, timezone

DEFAULT_NOW = "2026-01-01T00:00:00Z"


class LogicalClock:
    def __init__(self):
        self._now_dt = _parse_iso(DEFAULT_NOW)

    def now_dt(self):
        return self._now_dt

    def now_iso(self):
        return _format_iso(self._now_dt)

    def set(self, iso_value):
        self._now_dt = _parse_iso(iso_value)
        return self.now_iso()


def _parse_iso(value):
    """Parse an ISO-8601 instant (accepts trailing Z) into an aware UTC datetime."""
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_iso(value):
    """Public helper: parse an ISO instant for comparison. Raises ValueError on bad input."""
    return _parse_iso(value)


def _format_iso(dt):
    # ISO 8601 UTC with three fractional digits and a trailing Z.
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


clock = LogicalClock()
