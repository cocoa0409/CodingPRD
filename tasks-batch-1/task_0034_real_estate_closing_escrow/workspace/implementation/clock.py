"""Mock UTC clock for deterministic, test-drivable time.

PRD §3.8 — POST /_clock/set and /_clock/advance manipulate this clock; all
wall-clock fields (`created_at`, `updated_at`, `issued_at`, etc.) are sourced
from here so the 72-hour CD wait, 45-day identification deadline, and 180-day
exchange deadline are exercised deterministically.
"""
from __future__ import annotations

import datetime as dt
import threading


class Clock:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        # Default to real wall clock; tests override via /_clock/set or /_clock/advance.
        self._now: dt.datetime | None = None

    def now(self) -> dt.datetime:
        with self._lock:
            if self._now is not None:
                return self._now
            return dt.datetime.now(tz=dt.timezone.utc)

    def set(self, instant: dt.datetime) -> None:
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=dt.timezone.utc)
        else:
            instant = instant.astimezone(dt.timezone.utc)
        with self._lock:
            self._now = instant

    def advance(self, seconds: float) -> None:
        with self._lock:
            base = self._now if self._now is not None else dt.datetime.now(tz=dt.timezone.utc)
            self._now = base + dt.timedelta(seconds=seconds)


CLOCK = Clock()


def now_iso() -> str:
    """ISO 8601 UTC timestamp with exactly three fractional digits and trailing Z."""
    return format_iso(CLOCK.now())


def format_iso(instant: dt.datetime) -> str:
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=dt.timezone.utc)
    else:
        instant = instant.astimezone(dt.timezone.utc)
    # Compose YYYY-MM-DDTHH:MM:SS.mmmZ with exactly three fractional digits.
    millis = instant.microsecond // 1000
    return instant.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def parse_iso(s: str) -> dt.datetime:
    """Parse an ISO 8601 string (with optional fractional seconds and 'Z' or offset).

    Returns an aware UTC datetime.
    """
    if not isinstance(s, str):
        raise ValueError("not a string")
    raw = s.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"invalid ISO 8601 timestamp: {s}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    else:
        parsed = parsed.astimezone(dt.timezone.utc)
    return parsed
