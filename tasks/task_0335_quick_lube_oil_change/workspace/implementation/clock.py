"""Logical clock (PRD §3.12).

POST /_clock/set pins `now()` to a supplied UTC instant; until pinned, real
wall time is used. Clock state is process-local — every start.sh boot starts
unpinned (no carry-over under per-test-server isolation).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


_clock_override: Optional[datetime] = None


def now() -> datetime:
    """Return current UTC instant — the override if set, else wall time."""
    if _clock_override is not None:
        return _clock_override
    return datetime.now(timezone.utc)


def set_clock(dt: datetime) -> None:
    """Pin the logical clock to the supplied UTC datetime."""
    global _clock_override
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    _clock_override = dt


def iso(dt: Optional[datetime]) -> Optional[str]:
    """Render an aware datetime as ISO 8601 UTC with millisecond precision
    (three fractional digits, trailing Z) per PRD §2.4."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


def parse_iso(s) -> datetime:
    """Parse an ISO 8601 string into an aware UTC datetime."""
    if not isinstance(s, str) or not s:
        raise ValueError("not a string")
    raw = s.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt
