"""Logical clock with millisecond precision (ISO 8601 UTC)."""

from datetime import datetime, timezone, timedelta
from threading import RLock


class LogicalClock:
    def __init__(self):
        self._now = datetime.now(timezone.utc)
        self._lock = RLock()

    def now(self) -> datetime:
        with self._lock:
            return self._now

    def now_iso(self) -> str:
        return iso8601(self.now())

    def advance(self, seconds: float) -> datetime:
        with self._lock:
            self._now = self._now + timedelta(seconds=float(seconds))
            return self._now

    def set(self, dt: datetime):
        with self._lock:
            self._now = dt


def iso8601(dt: datetime) -> str:
    """Render a datetime as ISO 8601 UTC with three fractional digits and Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    # Build microseconds and round to milliseconds
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"


def parse_iso8601(s):
    """Parse an ISO 8601 datetime string. Returns datetime in UTC, or None on failure."""
    if s is None or not isinstance(s, str) or not s:
        return None
    try:
        # Accept variants with Z suffix
        if s.endswith("Z"):
            iso = s[:-1] + "+00:00"
        else:
            iso = s
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


clock = LogicalClock()
