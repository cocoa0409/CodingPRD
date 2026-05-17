"""Logical clock — monotonically advanceable for test-driving time-gated logic."""
from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock


class LogicalClock:
    """A clock that defaults to real UTC but can be advanced (never rewound) by tests."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._anchor: datetime | None = None  # set when /_clock/advance is called

    def now(self) -> datetime:
        with self._lock:
            if self._anchor is not None:
                return self._anchor
            return datetime.now(tz=timezone.utc)

    def advance_to(self, target: datetime) -> datetime:
        """Set the clock to `target`. `target` must be >= the previously
        anchored logical instant. Until an anchor has been set, the first
        advance_to call accepts any timestamp — there is no prior
        logical instant to be moved backwards from."""
        with self._lock:
            if self._anchor is not None and target < self._anchor:
                # Monotonicity violation — surfaced as ERR_INVALID_INPUT by the route.
                raise ValueError("clock cannot be moved backwards")
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


def iso_format(dt: datetime) -> str:
    """ISO 8601 UTC with three fractional digits, e.g. 2025-05-24T10:30:00.123Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"
