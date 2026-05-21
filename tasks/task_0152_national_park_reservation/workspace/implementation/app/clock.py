"""Virtual clock service controlled via POST /_clock/advance."""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Optional

from .util import parse_iso8601


_CLOCK_LOCK = threading.RLock()
_virtual_now: Optional[datetime] = None


def now_utc() -> datetime:
    """Return the current virtual UTC time, or real UTC if never set."""
    with _CLOCK_LOCK:
        if _virtual_now is not None:
            return _virtual_now
    return datetime.now(tz=timezone.utc)


def advance_to(target_iso: str) -> datetime:
    """Set the virtual clock to target_iso. Raises ValueError on bad input."""
    global _virtual_now
    dt = parse_iso8601(target_iso)
    if dt is None:
        raise ValueError("target_iso must be ISO 8601 UTC")
    with _CLOCK_LOCK:
        _virtual_now = dt
    return dt
