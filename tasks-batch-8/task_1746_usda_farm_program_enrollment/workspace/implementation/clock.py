"""Logical clock for deadline/window checks.

The server's startup default is 2026-08-01T00:00:00Z; before any
clock-setting call the clock reads exactly this default and never
falls back to wall-clock time (PRD §2.9).
"""

from datetime import datetime, timezone

_DEFAULT_ISO = "2026-08-01T00:00:00Z"


def _parse_iso(value):
    """Parse an ISO-8601 string, accepting a trailing 'Z' for UTC."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class LogicalClock:
    def __init__(self):
        self._current = _parse_iso(_DEFAULT_ISO)

    def now(self):
        return self._current

    def set(self, iso_value):
        self._current = _parse_iso(iso_value)
        return self._current

    def now_iso(self):
        return iso_z(self._current)


def iso_z(dt):
    """Format a datetime as ISO 8601 UTC with three fractional digits."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{dt.microsecond // 1000:03d}Z"


# Module-level singleton clock (logical time — not wall clock).
CLOCK = LogicalClock()


def now_dt():
    return CLOCK.now()


def now_iso():
    return iso_z(CLOCK.now())
