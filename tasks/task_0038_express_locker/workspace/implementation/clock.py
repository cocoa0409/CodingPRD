"""Virtual clock used by the test harness — driven via POST /_clock/advance."""

import threading
from datetime import datetime, timezone, timedelta


class VirtualClock:
    def __init__(self):
        self._lock = threading.RLock()
        self._now = None  # None means use wall clock

    def now(self) -> datetime:
        with self._lock:
            if self._now is not None:
                dt = self._now
            else:
                dt = datetime.now(timezone.utc)
        # Truncate to millisecond precision so the value the API serializes
        # (3 fractional digits) round-trips exactly when a client advances
        # the clock back to the timestamp we returned.
        millis = dt.microsecond // 1000
        return dt.replace(microsecond=millis * 1000)

    def advance_seconds(self, seconds: float) -> datetime:
        with self._lock:
            current = self._now if self._now is not None else datetime.now(timezone.utc)
            current_millis = current.microsecond // 1000
            current = current.replace(microsecond=current_millis * 1000)
            new_now = current + timedelta(seconds=float(seconds))
            millis = new_now.microsecond // 1000
            new_now = new_now.replace(microsecond=millis * 1000)
            self._now = new_now
            return self._now

    def reset(self):
        with self._lock:
            self._now = None


CLOCK = VirtualClock()


def now() -> datetime:
    return CLOCK.now()


def now_iso() -> str:
    n = CLOCK.now()
    if n.tzinfo is None:
        n = n.replace(tzinfo=timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def parse_iso(value):
    """Parse an ISO 8601 string to an aware datetime (UTC)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if not isinstance(value, str):
        raise ValueError("Expected ISO 8601 timestamp string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except Exception as exc:
        raise ValueError(f"Invalid timestamp: {value}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt) -> str:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
