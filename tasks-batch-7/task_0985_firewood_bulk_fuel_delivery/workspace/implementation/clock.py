"""Logical clock per PRD §2.5.

The server maintains a logical clock initialized to exactly 2026-05-01T00:00:00Z
on startup. Nothing in the system reads wall-clock time directly for business
logic.
"""

from datetime import datetime, timezone


_INITIAL = "2026-05-01T00:00:00Z"


def _parse_iso(s):
    """Parse ISO 8601 string, accepting trailing Z."""
    if s is None:
        return None
    if isinstance(s, datetime):
        return s
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _format_iso(dt):
    """Format datetime as ISO 8601 UTC with Z suffix."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class LogicalClock:
    def __init__(self):
        self._current = _parse_iso(_INITIAL)

    def now(self):
        return self._current

    def now_iso(self):
        return _format_iso(self._current)

    def set(self, to_iso8601):
        self._current = _parse_iso(to_iso8601)
        return self._current


clock = LogicalClock()
