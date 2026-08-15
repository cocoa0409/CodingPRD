"""Logical clock (PRD 2.4). Starts at exactly 2026-08-01T00:00:00Z and never
falls back to wall-clock time. Advanced only via POST /_clock/set_current_utc.
All server-emitted timestamps derive from this clock."""
from datetime import datetime, timezone

_DEFAULT = "2026-08-01T00:00:00Z"


def parse_iso(s):
    """Parse an ISO 8601 timestamp to an aware UTC datetime. Raises on garbage."""
    if isinstance(s, datetime):
        dt = s
    elif isinstance(s, str):
        v = s.strip()
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"
        dt = datetime.fromisoformat(v)
    else:
        raise ValueError("not an ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix (PRD 2.5)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


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
