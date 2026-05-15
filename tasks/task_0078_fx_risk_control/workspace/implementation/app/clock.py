"""Server-side clock that can be advanced from tests."""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Optional


class ServerClock:
    """Monotonic, advance-only logical clock.

    When no override has been set we delegate to real wall-clock time.
    Tests drive deterministic time-gated transitions by calling
    `set_to_iso()` (mapped to `POST /_clock/advance`).
    """

    def __init__(self) -> None:
        self._override: Optional[datetime] = None
        self._lock = threading.RLock()

    # --- read helpers -----------------------------------------------------
    def now(self) -> datetime:
        with self._lock:
            if self._override is not None:
                return self._override
            return datetime.now(timezone.utc)

    def now_iso(self) -> str:
        return format_iso(self.now())

    def today_iso_date(self) -> str:
        return self.now().strftime("%Y-%m-%d")

    # --- mutation ---------------------------------------------------------
    def set_to_iso(self, iso: str) -> datetime:
        target = parse_iso(iso)
        with self._lock:
            self._override = target
        return target

    def reset(self) -> None:
        """Clear any test override so the clock falls back to real time.

        Used by the test-only /_test/reset endpoint between tests."""
        with self._lock:
            self._override = None


def parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 instant.  Accept trailing Z, fractional seconds."""
    if not isinstance(value, str) or not value:
        raise ValueError("invalid ISO 8601 string")
    # Normalise Zulu suffix
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError as exc:
        raise ValueError("invalid ISO 8601 string") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso(dt: datetime) -> str:
    """ISO 8601 UTC with exactly three fractional digits, Zulu suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    ms = int(dt.microsecond / 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


# Module-level singleton; routes import this directly.
clock = ServerClock()
