"""Logical clock used by overdue sweeps. Tests advance this clock explicitly."""
from datetime import datetime, timezone
from threading import RLock
from typing import Optional


class LogicalClock:
    def __init__(self) -> None:
        self._lock = RLock()
        self._override: Optional[datetime] = None

    def now(self) -> datetime:
        with self._lock:
            if self._override is not None:
                return self._override
            return datetime.now(tz=timezone.utc)

    def set(self, instant: datetime) -> None:
        with self._lock:
            if instant.tzinfo is None:
                instant = instant.replace(tzinfo=timezone.utc)
            else:
                instant = instant.astimezone(timezone.utc)
            self._override = instant


clock = LogicalClock()


def iso_now() -> str:
    """Return current logical-clock time as ISO 8601 UTC with milliseconds."""
    return format_iso(clock.now())


def format_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 string into a tz-aware UTC datetime."""
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError as exc:
        raise ValueError(f"invalid ISO 8601 timestamp: {value}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
