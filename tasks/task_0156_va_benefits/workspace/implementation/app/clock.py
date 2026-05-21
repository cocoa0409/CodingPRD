"""Logical server clock with test-driver advance support."""
from __future__ import annotations

import threading
from datetime import datetime, timezone


class Clock:
    """A monotonically-advanceable logical clock.

    Tests may advance the clock via POST /_clock/advance — either by jumping to
    a specific ISO 8601 instant or by adding a positive integer number of
    seconds. The clock never moves backwards in production code; if a 'to'
    target is in the past the request is silently coerced to a no-op (we leave
    behavior verification to the validation layer if the spec mandates).
    """

    _ISO_FMT = "%Y-%m-%dT%H:%M:%S.%fZ"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._now: datetime = datetime.now(tz=timezone.utc)

    def now(self) -> datetime:
        with self._lock:
            return self._now

    def now_iso(self) -> str:
        return self.format(self.now())

    def advance_to(self, target: datetime) -> datetime:
        with self._lock:
            if target > self._now:
                self._now = target
            return self._now

    def advance_seconds(self, seconds: int) -> datetime:
        from datetime import timedelta

        with self._lock:
            self._now = self._now + timedelta(seconds=seconds)
            return self._now

    @staticmethod
    def format(dt: datetime) -> str:
        """Return ISO 8601 UTC string with three fractional digits."""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        # millisecond precision
        ms = int(dt.microsecond / 1000)
        base = dt.strftime("%Y-%m-%dT%H:%M:%S")
        return f"{base}.{ms:03d}Z"

    @staticmethod
    def parse(s: str) -> datetime:
        """Parse an ISO 8601 timestamp into an aware UTC datetime."""
        if not isinstance(s, str):
            raise ValueError("timestamp must be a string")
        v = s.strip()
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(v)
        except ValueError as exc:
            raise ValueError(f"invalid ISO 8601 timestamp: {s}") from exc
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt
