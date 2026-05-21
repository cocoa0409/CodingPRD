"""Server-side logical clock. Used for every time-gated transition."""

from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from typing import Optional


_lock = Lock()
_logical_now: Optional[datetime] = None


def _real_now() -> datetime:
    return datetime.now(timezone.utc)


def now() -> datetime:
    with _lock:
        if _logical_now is None:
            return _real_now()
        return _logical_now


def advance_to(target: datetime) -> datetime:
    """Set the logical clock to `target`. Backward motion not allowed."""
    global _logical_now
    with _lock:
        current = _logical_now if _logical_now is not None else _real_now()
        if target < current:
            raise ValueError("Cannot move logical clock backward")
        _logical_now = target
        return _logical_now


def reset() -> None:
    """Test-only helper. Not exposed via HTTP."""
    global _logical_now
    with _lock:
        _logical_now = None
