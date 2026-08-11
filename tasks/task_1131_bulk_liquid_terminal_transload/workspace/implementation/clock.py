"""Logical clock. Starts at exactly 2026-05-01T00:00:00Z; never falls back
to wall-clock time. Advanced only via POST /_clock/set_current_utc."""
from datetime import datetime, timezone

_DEFAULT_ISO = "2026-05-01T00:00:00Z"


def _parse_iso(value):
    """Parse an ISO-8601 datetime string into an aware UTC datetime.

    Returns None when the value is not a string or cannot be parsed.
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_z(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{dt.microsecond // 1000:03d}Z"


class LogicalClock:
    def __init__(self):
        self._now = _parse_iso(_DEFAULT_ISO)

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt
        return self._now


# Module-level singleton; a fresh process always starts at the default.
CLOCK = LogicalClock()
