"""Test clock — supports POST /_clock/advance to deterministically move time."""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

_lock = threading.Lock()
_offset_seconds: float = 0.0


def now_utc() -> datetime:
    base = datetime.now(timezone.utc)
    return base + timedelta(seconds=_offset_seconds)


def now_iso() -> str:
    """ISO 8601 UTC with 3 fractional digits, e.g. 2025-05-24T10:30:00.123Z"""
    dt = now_utc()
    millis = int(dt.microsecond / 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{millis:03d}Z"


def advance(seconds: int) -> None:
    global _offset_seconds
    with _lock:
        _offset_seconds += float(seconds)


def today_utc_date():
    return now_utc().date()
