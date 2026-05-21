"""Logical clock — supports the admin /_clock/advance hook (§3.10)."""
from __future__ import annotations

import threading
from datetime import datetime, timezone


_lock = threading.Lock()
_logical_now: datetime | None = None


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
    """Advance the logical clock — past-direction moves are no-ops (§3.10)."""
    global _logical_now
    if to.tzinfo is None:
        to = to.replace(tzinfo=timezone.utc)
    else:
        to = to.astimezone(timezone.utc)
    with _lock:
        if _logical_now is None:
            # First-ever advance establishes the logical clock at `to`. Tests rely on this
            # to deterministically set time even when `to` is in the past relative to wall time.
            _logical_now = to
        else:
            if to > _logical_now:
                _logical_now = to
            # else: idempotent no-op (past-direction is rejected silently per §3.10)


def iso_format(dt: datetime) -> str:
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    return f"{base}.{ms:03d}Z"


def parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 datetime; accepts trailing Z or explicit offset."""
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
