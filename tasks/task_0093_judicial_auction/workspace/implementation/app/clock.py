"""Logical clock with absolute set / advance — driven by POST /_clock/advance."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional


def parse_iso(value) -> datetime:
    """Parse an ISO-8601 timestamp; raises ValueError on failure."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        raise ValueError(f"Invalid timestamp type: {type(value).__name__}")
    v = value.strip()
    try:
        if v.endswith("Z"):
            return datetime.fromisoformat(v[:-1] + "+00:00")
        return datetime.fromisoformat(v)
    except ValueError:
        raise ValueError(f"Unparseable timestamp: {value!r}")


def format_iso(dt: Optional[datetime]) -> Optional[str]:
    """ISO-8601 UTC with three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class _Clock:
    """Simulated server clock.

    PRD §3.5: "an admin-only capability advances the simulated server
    clock to a supplied `to` instant". A simulated clock is logical,
    not wall-driven: once set to an instant, subsequent reads return
    that same instant (frozen) until the next advance call. This is
    what makes strict-less-than boundary tests deterministic.

    When no advance has happened yet, the clock tracks wall time so
    "now" stays sensible for fresh installs (created_at timestamps).
    """

    def __init__(self) -> None:
        self._frozen_at: Optional[datetime] = None

    @property
    def now(self) -> datetime:
        if self._frozen_at is not None:
            return self._frozen_at
        return datetime.now(tz=timezone.utc)

    def set(self, dt: datetime) -> None:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        self._frozen_at = dt

    def advance(self, seconds: float) -> None:
        base = self._frozen_at or datetime.now(tz=timezone.utc)
        self._frozen_at = base + timedelta(seconds=float(seconds))

    def reset(self) -> None:
        self._frozen_at = None


CLOCK = _Clock()


def now_dt() -> datetime:
    return CLOCK.now


def now_iso_ms() -> str:
    return format_iso(CLOCK.now)  # type: ignore[return-value]


def add_hours(dt: datetime, hours: float) -> datetime:
    return dt + timedelta(hours=hours)


def add_days(dt: datetime, days: float) -> datetime:
    return dt + timedelta(days=days)
