"""Logical clock. Starts at exactly 2026-08-01T00:00:00Z; never falls back to
wall-clock time. Advanced only via POST /_clock/set_current_utc."""

from datetime import datetime, timezone

_DEFAULT = "2026-08-01T00:00:00Z"


def parse_iso(s):
    if s is None:
        return None
    if isinstance(s, datetime):
        return s.astimezone(timezone.utc)
    if not isinstance(s, str):
        raise ValueError("not an ISO timestamp")
    v = s.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso(dt):
    """Format a datetime as ISO 8601 UTC with three fractional digits and Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    ms = dt.microsecond // 1000
    return f"{base}.{ms:03d}Z"


class _Clock:
    def __init__(self):
        self._now = parse_iso(_DEFAULT)

    def now(self):
        return self._now

    def now_iso(self):
        return format_iso(self._now)

    def set(self, value):
        self._now = parse_iso(value)
        return self._now


CLOCK = _Clock()
