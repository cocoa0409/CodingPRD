from __future__ import annotations

"""Logical clock — advanceable via /ethics/_clock/advance for test driving."""

from datetime import datetime, timezone
from threading import RLock


_lock = RLock()
_logical_now: datetime | None = None  # if None, uses real wall-clock


def now() -> datetime:
    """Return the current logical UTC datetime."""
    with _lock:
        if _logical_now is not None:
            return _logical_now
        return datetime.now(timezone.utc)


def advance_to(ts: datetime) -> None:
    """Pin the logical clock to ts (must be tz-aware UTC)."""
    with _lock:
        global _logical_now
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        else:
            ts = ts.astimezone(timezone.utc)
        _logical_now = ts


def reset() -> None:
    with _lock:
        global _logical_now
        _logical_now = None


def iso(ts: datetime | None = None) -> str:
    """ISO 8601 UTC with three fractional digits, 'Z' suffix."""
    if ts is None:
        ts = now()
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    else:
        ts = ts.astimezone(timezone.utc)
    # Format with milliseconds (3 fractional digits)
    s = ts.strftime("%Y-%m-%dT%H:%M:%S")
    ms = ts.microsecond // 1000
    return f"{s}.{ms:03d}Z"


def parse_iso(s: str) -> datetime:
    """Parse ISO 8601 UTC datetime; raise ValueError on malformed input."""
    if not isinstance(s, str) or not s:
        raise ValueError("datetime must be a non-empty string")
    # Accept trailing Z
    raw = s
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError as e:
        raise ValueError(f"malformed datetime: {s}") from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt
