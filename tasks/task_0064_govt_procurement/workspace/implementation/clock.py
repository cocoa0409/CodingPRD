"""Server-side virtual clock.

Initialised to 1970-01-01T00:00:00.000Z on first boot.
Advanced only via POST /_clock/advance with a target_iso parameter.
Idempotent on identical target_iso.
"""

import threading
from datetime import datetime, timezone


_EPOCH_ISO = "1970-01-01T00:00:00.000Z"


def _parse_iso(s: str) -> datetime:
    """Parse an ISO 8601 string into an aware UTC datetime."""
    if not isinstance(s, str) or not s:
        raise ValueError("invalid iso timestamp")
    # Normalise trailing Z -> +00:00
    raw = s.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except Exception as e:
        raise ValueError(f"invalid iso timestamp: {s}") from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def _format_iso(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(dt.microsecond / 1000):03d}Z"


class VirtualClock:
    def __init__(self):
        self._lock = threading.RLock()
        self._dt = _parse_iso(_EPOCH_ISO)

    def now(self) -> datetime:
        with self._lock:
            return self._dt

    def now_iso(self) -> str:
        return _format_iso(self.now())

    def advance_to(self, target_iso: str) -> datetime:
        """Move forward to target_iso. Idempotent: if already at target, no-op.
        Never moves backward.
        """
        target = _parse_iso(target_iso)
        with self._lock:
            if target > self._dt:
                self._dt = target
            return self._dt


clock = VirtualClock()


def parse_iso(s: str) -> datetime:
    return _parse_iso(s)


def format_iso(dt: datetime) -> str:
    return _format_iso(dt)
