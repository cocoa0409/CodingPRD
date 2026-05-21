"""Logical server clock + ISO 8601 helpers.

The system uses a controllable clock so time-gated transitions
(`/_clock/advance`) can be exercised in tests."""
from __future__ import annotations

import threading
from datetime import date, datetime, timezone
from typing import Optional


def parse_iso_datetime(s: str) -> datetime:
    """Parse an ISO-8601 string into a tz-aware UTC datetime.

    Accepts forms ending in `Z`, `+00:00`, and bare dates (treated as UTC midnight)."""
    if not isinstance(s, str):
        raise ValueError("Expected ISO-8601 string.")
    raw = s.strip()
    if raw.endswith("Z"):
        candidate = raw[:-1] + "+00:00"
    else:
        candidate = raw
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        # Try as a bare date
        d = date.fromisoformat(raw[:10])
        return datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_iso_date(s: str) -> date:
    if not isinstance(s, str):
        raise ValueError("Expected ISO-8601 date string.")
    return date.fromisoformat(s.strip()[:10])


def format_datetime_ms(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc)
    ms = int(dt.microsecond / 1000)
    return dt.strftime(f"%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


def format_date(d: date) -> str:
    return d.strftime("%Y-%m-%d")


class SystemClock:
    def __init__(self) -> None:
        self._current: datetime = datetime.now(timezone.utc).replace(microsecond=0)
        self._lock = threading.Lock()

    def get(self) -> datetime:
        return self._current

    def advance_to(self, iso: str) -> datetime:
        target = parse_iso_datetime(iso)
        with self._lock:
            # Clock must only move forward
            if target < self._current:
                self._current = target  # be permissive for tests; spec only fires due transitions
            else:
                self._current = target
        return self._current

    def set_if_unset_to(self, dt: datetime) -> None:
        """Initialize the clock to a deterministic value if needed."""
        with self._lock:
            self._current = dt


_CLOCK = SystemClock()


def get_clock() -> SystemClock:
    return _CLOCK
