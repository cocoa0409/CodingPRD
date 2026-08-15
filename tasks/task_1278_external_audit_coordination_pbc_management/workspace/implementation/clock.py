"""Logical clock. Boots pinned to 2026-08-01T00:00:00Z. Advanced only via
POST /api/_clock/set_current_utc. All server-written timestamps read here.
"""
import threading
from datetime import datetime, timezone


_BOOT_INSTANT = "2026-08-01T00:00:00Z"


class LogicalClock:
    def __init__(self):
        self._lock = threading.Lock()
        self._now = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        with self._lock:
            return self._now

    def set(self, dt):
        with self._lock:
            self._now = dt

    def now_iso(self):
        return format_iso(self.now())


def format_iso(dt):
    """Format a datetime as ISO 8601 UTC with three fractional digits, e.g.
    2026-08-01T00:00:00.000Z"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


def parse_iso(value):
    """Parse an ISO 8601 timestamp into an aware UTC datetime.
    Accepts 'Z' suffix or explicit offsets; also accepts date-only strings."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse a YYYY-MM-DD date string into a date."""
    from datetime import date as _date
    if not isinstance(value, str):
        raise ValueError("not a string")
    parts = value.strip().split("-")
    if len(parts) != 3:
        raise ValueError("bad date")
    y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
    return _date(y, m, d)


clock = LogicalClock()
