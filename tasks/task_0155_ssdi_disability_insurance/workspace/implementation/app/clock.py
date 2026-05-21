"""Server-side logical clock (PRD §2.10).

Every time-gated transition (appeal window, hold/no-show/reschedule,
CDR scheduling, etc.) consults `now()`. PlatformAdmin can call
`POST /_clock/advance` to fast-forward the logical clock.
"""

from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from typing import Optional


_lock = Lock()
_logical_now: Optional[datetime] = None


def _real_now() -> datetime:
    return datetime.now(timezone.utc)


def now() -> datetime:
    """Return the current logical instant (UTC-aware datetime)."""
    with _lock:
        if _logical_now is None:
            return _real_now()
        return _logical_now


def advance_to(target: datetime) -> datetime:
    """Move the logical clock to `target`. Monotonically non-decreasing."""
    global _logical_now
    with _lock:
        current = _logical_now if _logical_now is not None else _real_now()
        if target < current:
            # Clock cannot move backwards; treat as a no-op.
            return current
        _logical_now = target
        return _logical_now


def reset() -> None:
    """Test-only helper. Not exposed via HTTP."""
    global _logical_now
    with _lock:
        _logical_now = None
