"""Logical server clock that supports test-driven advancement.

PRD §3.5: "The clock-advance capability ... accepts a `seconds`
argument and shifts the server's logical now() forward by that many
seconds." The test suite "drives the entire long-stay → return →
disposal arc deterministically." Deterministic advancement requires a
frozen logical base time — otherwise wall-clock drift between
registration and pickup violates exact-boundary expectations.
"""
from datetime import datetime, timezone, timedelta
import threading

_lock = threading.Lock()
# Frozen base captured at process start; logical time = _base + _offset.
_base = datetime.now(timezone.utc)
_offset_seconds = 0.0


def now() -> datetime:
    """Return the current logical server time (UTC)."""
    with _lock:
        return _base + timedelta(seconds=_offset_seconds)


def advance(seconds: float) -> datetime:
    """Move the logical clock forward by `seconds` and return the new now()."""
    global _offset_seconds
    with _lock:
        _offset_seconds += float(seconds)
        return _base + timedelta(seconds=_offset_seconds)


def iso(dt: datetime) -> str:
    """Format a datetime as ISO 8601 UTC with milliseconds and Z suffix."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    # Force exactly 3 fractional digits + Z
    s = dt.strftime("%Y-%m-%dT%H:%M:%S")
    ms = f"{dt.microsecond // 1000:03d}"
    return f"{s}.{ms}Z"


def now_iso() -> str:
    return iso(now())
