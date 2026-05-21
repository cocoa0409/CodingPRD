"""Time, ID, decimal helpers for the Fantasy Football League API."""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional


_LOCK = threading.RLock()


def lock():
    return _LOCK


def new_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    """Server wall-clock ISO 8601 UTC timestamp with millisecond precision."""
    return format_iso(datetime.now(timezone.utc))


def format_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    ms = int(dt.microsecond / 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"


def parse_iso(value) -> Optional[datetime]:
    """Parse an ISO 8601 string into a UTC aware datetime."""
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError("Expected non-empty ISO 8601 string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError as exc:
        raise ValueError(f"Invalid ISO 8601 string: {value}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def round_half_up_2dp(value) -> float:
    """Round to two decimal places half-up; returns float."""
    d = Decimal(str(value))
    quantized = d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(quantized)


def is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def is_number(value) -> bool:
    if isinstance(value, bool):
        return False
    return isinstance(value, (int, float))


def is_string(value) -> bool:
    return isinstance(value, str)
