"""Logical clock with an admin-driven /_clock/advance hook."""
from __future__ import annotations

import threading
from datetime import datetime, timezone


_lock = threading.Lock()
_logical_now: datetime | None = None  # When set, server uses this instead of wall clock.


def _real_now() -> datetime:
    return datetime.now(timezone.utc)


def now() -> datetime:
    with _lock:
        if _logical_now is not None:
            return _logical_now
        return _real_now()


def now_iso() -> str:
    return iso_format(now())


def set_clock(to: datetime) -> None:
    global _logical_now
    if to.tzinfo is None:
        to = to.replace(tzinfo=timezone.utc)
    else:
        to = to.astimezone(timezone.utc)
    with _lock:
        _logical_now = to


def iso_format(dt: datetime) -> str:
    """Render UTC ISO 8601 with exactly three fractional digits and a Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    return f"{base}.{ms:03d}Z"


def parse_iso(value):
    """Parse an ISO 8601 string. Accepts trailing 'Z' or explicit offset."""
    if value is None:
        raise ValueError("missing timestamp")
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    v = value.strip()
    if v.endswith("Z") or v.endswith("z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except ValueError as exc:
        raise ValueError(f"invalid ISO 8601 timestamp: {value}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
