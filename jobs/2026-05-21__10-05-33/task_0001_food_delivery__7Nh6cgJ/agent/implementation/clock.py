"""Logical clock used for all timestamp generation in the platform."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone


class LogicalClock:
    """Wall-clock with an admin-controlled offset (in seconds)."""

    def __init__(self) -> None:
        self._offset_seconds: float = 0.0
        self._lock = threading.RLock()

    def advance(self, seconds: float) -> None:
        with self._lock:
            self._offset_seconds += float(seconds)

    def now(self) -> datetime:
        with self._lock:
            return datetime.fromtimestamp(
                time.time() + self._offset_seconds, tz=timezone.utc
            )

    def now_iso(self) -> str:
        return iso_ms(self.now())


def iso_ms(dt: datetime) -> str:
    """ISO 8601 UTC timestamp with exactly three fractional digits, e.g. 2025-05-24T10:30:00.123Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    ms = int(dt.microsecond / 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"


CLOCK = LogicalClock()
