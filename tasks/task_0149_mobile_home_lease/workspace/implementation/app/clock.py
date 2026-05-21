"""Logical clock for the API. Advances via POST /_clock/advance."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import Lock


class LogicalClock:
    """A monotonically advancing UTC clock that supports manual advance."""

    def __init__(self) -> None:
        self._offset = timedelta(seconds=0)
        self._origin = datetime.now(tz=timezone.utc)
        self._lock = Lock()

    def now(self) -> datetime:
        with self._lock:
            return datetime.now(tz=timezone.utc) + self._offset

    def advance(self, seconds: float) -> None:
        with self._lock:
            self._offset += timedelta(seconds=seconds)

    def iso_now(self) -> str:
        return format_timestamp(self.now())


def format_timestamp(dt: datetime) -> str:
    """Format a datetime as ISO 8601 UTC with millisecond precision (3 fractional digits)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    # Force millisecond precision
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{millis:03d}Z"


clock = LogicalClock()


__all__ = ["clock", "format_timestamp", "LogicalClock"]
