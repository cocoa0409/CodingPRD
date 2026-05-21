"""Time, ID, decimal, and date helpers."""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional


_LOCK = threading.RLock()


def lock():
    """Return the global re-entrant lock used to serialize all writes."""
    return _LOCK


def new_id() -> str:
    """Generate a UUIDv4 string without any type prefix."""
    return str(uuid.uuid4())


def now_iso() -> str:
    """Server wall-clock for response envelopes (ISO 8601 UTC, ms precision)."""
    return format_iso(datetime.now(timezone.utc))


def format_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    ms = int(dt.microsecond / 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"


def parse_iso(value) -> Optional[datetime]:
    """Parse an ISO 8601 string into a timezone-aware UTC datetime."""
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


def round_half_up(value) -> int:
    """Round a number (int/float/Decimal) half-up to the nearest integer."""
    d = Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_cents(numerator: Decimal) -> int:
    """Round a Decimal to integer cents using half-up."""
    return int(numerator.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def is_uuid(value) -> bool:
    """Check whether a string is a well-formed UUID."""
    if not isinstance(value, str) or not value:
        return False
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False


def is_int(value) -> bool:
    """Strictly check int (not bool)."""
    return isinstance(value, int) and not isinstance(value, bool)


def is_number(value) -> bool:
    """Allow int or float, but not bool."""
    if isinstance(value, bool):
        return False
    return isinstance(value, (int, float))
