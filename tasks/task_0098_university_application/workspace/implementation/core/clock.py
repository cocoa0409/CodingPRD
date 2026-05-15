"""Server-controlled clock with test-driving advance capability."""
from __future__ import annotations
import threading
from datetime import datetime, timedelta, timezone


class Clock:
    def __init__(self) -> None:
        self._offset_seconds: float = 0.0
        self._lock = threading.Lock()

    def now(self) -> datetime:
        return datetime.now(tz=timezone.utc) + timedelta(seconds=self._offset_seconds)

    def advance(self, seconds: float) -> None:
        with self._lock:
            self._offset_seconds += float(seconds)

    def iso(self) -> str:
        return format_iso(self.now())


def format_iso(dt: datetime) -> str:
    """Format a datetime as ISO 8601 UTC with three fractional digits and Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


clock = Clock()
