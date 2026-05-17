"""Deterministic logical clock — anchored value advanced via /practice/_clock/advance."""
from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock


class LogicalClock:
    """A deterministic logical clock. Anchor defaults to real UTC, but tests advance it."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._anchor: datetime | None = None

    def now(self) -> datetime:
        with self._lock:
            if self._anchor is not None:
                return self._anchor
            return datetime.now(tz=timezone.utc)

    def advance_to(self, target: datetime) -> datetime:
        with self._lock:
            self._anchor = target
            return target

    def reset(self) -> None:
        with self._lock:
            self._anchor = None


clock = LogicalClock()


def now() -> datetime:
    return clock.now()


def now_iso() -> str:
    return iso_format(clock.now())


def iso_format(dt: datetime | None) -> str | None:
    """ISO 8601 UTC with three fractional digits, e.g. 2025-05-24T10:30:00.123Z."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"
