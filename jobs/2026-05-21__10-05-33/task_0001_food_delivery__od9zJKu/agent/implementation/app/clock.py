"""Logical wall-clock that supports admin-driven advancement."""
from __future__ import annotations

import datetime as _dt
import threading


class LogicalClock:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._offset_seconds: float = 0.0

    def advance(self, seconds: float) -> None:
        with self._lock:
            self._offset_seconds += float(seconds)

    def now(self) -> _dt.datetime:
        return _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(seconds=self._offset_seconds)

    def reset(self) -> None:
        with self._lock:
            self._offset_seconds = 0.0


clock = LogicalClock()


def iso_now() -> str:
    """ISO 8601 UTC with three fractional digits, e.g. 2025-05-24T10:30:00.123Z."""
    t = clock.now()
    s = t.strftime("%Y-%m-%dT%H:%M:%S")
    ms = int(t.microsecond / 1000)
    return f"{s}.{ms:03d}Z"


def iso_format(dt: _dt.datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    else:
        dt = dt.astimezone(_dt.timezone.utc)
    s = dt.strftime("%Y-%m-%dT%H:%M:%S")
    ms = int(dt.microsecond / 1000)
    return f"{s}.{ms:03d}Z"
