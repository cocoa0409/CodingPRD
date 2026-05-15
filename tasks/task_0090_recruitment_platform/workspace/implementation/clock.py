"""Logical clock for the recruitment platform.

All timestamps used by the application flow through this clock so tests can
deterministically advance time via the /recruitment/_clock/advance endpoint.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


class _Clock:
    def __init__(self) -> None:
        self._frozen: Optional[datetime] = None

    def now(self) -> datetime:
        if self._frozen is not None:
            return self._frozen
        return datetime.now(timezone.utc)

    def set(self, value: datetime) -> None:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        else:
            value = value.astimezone(timezone.utc)
        self._frozen = value


clock = _Clock()


def iso_now() -> str:
    return format_iso(clock.now())


def format_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    # ISO 8601 UTC with three fractional digits and a trailing 'Z'.
    ms = int(dt.microsecond / 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"


def parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 timestamp. Accepts trailing Z or explicit offsets."""
    if not isinstance(value, str) or not value:
        raise ValueError("invalid datetime string")
    s = value.strip()
    # Normalize trailing Z to +00:00 for fromisoformat.
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError as e:
        raise ValueError(str(e))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt
