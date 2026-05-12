"""Virtual clock — driven via POST /_clock/advance. PRD §3.11."""

import threading
from datetime import datetime, timezone, timedelta


class VirtualClock:
    def __init__(self):
        self._lock = threading.RLock()
        # Pin the clock at process start so the system has a deterministic notion of "now".
        n = datetime.now(timezone.utc)
        millis = n.microsecond // 1000
        self._now = n.replace(microsecond=millis * 1000)

    def now(self) -> datetime:
        with self._lock:
            return self._now

    def advance_seconds(self, seconds: int) -> datetime:
        with self._lock:
            self._now = self._now + timedelta(seconds=int(seconds))
            return self._now

    def reset(self):
        with self._lock:
            n = datetime.now(timezone.utc)
            millis = n.microsecond // 1000
            self._now = n.replace(microsecond=millis * 1000)


CLOCK = VirtualClock()


def now() -> datetime:
    return CLOCK.now()


def now_iso() -> str:
    n = CLOCK.now()
    if n.tzinfo is None:
        n = n.replace(tzinfo=timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def to_iso(dt: datetime) -> str:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value):
    """Parse an ISO 8601 string into an aware UTC datetime."""
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
