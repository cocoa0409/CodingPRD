"""Logical clock controlling all timestamps."""
from datetime import datetime, timezone
from threading import RLock


class LogicalClock:
    def __init__(self):
        self._now = None  # datetime in UTC
        self._lock = RLock()

    def now(self) -> datetime:
        with self._lock:
            if self._now is None:
                return datetime.now(timezone.utc)
            return self._now

    def set(self, dt: datetime):
        with self._lock:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            self._now = dt

    def now_iso(self) -> str:
        return format_iso8601(self.now())


def format_iso8601(dt: datetime) -> str:
    """ISO 8601 UTC with exactly 3 fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso8601(s: str) -> datetime:
    """Parse ISO 8601 - flexible. Returns UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except Exception as e:
        raise ValueError(f"Invalid ISO 8601: {s}") from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


clock = LogicalClock()
