"""Logical clock — server-controlled datetime that tests advance manually."""
from datetime import datetime, timezone
from threading import RLock


class LogicalClock:
    def __init__(self):
        self._lock = RLock()
        # Start at the current wall-clock time (UTC), truncated to ms.
        wall = datetime.now(timezone.utc)
        self._now = wall.replace(microsecond=(wall.microsecond // 1000) * 1000)

    def now(self) -> datetime:
        with self._lock:
            return self._now

    def advance_to(self, target: datetime) -> datetime:
        with self._lock:
            self._now = target
            return self._now


clock = LogicalClock()


def iso8601_ms(dt: datetime) -> str:
    """Format a datetime as ISO 8601 UTC with millisecond precision and Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso8601(value: str) -> datetime:
    """Parse an ISO 8601 string into a tz-aware UTC datetime. Raises ValueError on bad input."""
    if not isinstance(value, str) or not value:
        raise ValueError("invalid datetime")
    s = value.strip()
    # Normalize trailing Z to +00:00 for fromisoformat compatibility.
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except Exception as exc:
        raise ValueError(f"invalid datetime: {value}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt
