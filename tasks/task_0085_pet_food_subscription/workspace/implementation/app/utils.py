"""Generic utility helpers: timestamps, ids, rounding."""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

from app.clock import logical_clock


_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(Z|[+\-]\d{2}:?\d{2})$"
)


def new_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    """Wall-clock UTC ISO 8601 timestamp with ms precision (for envelope only)."""
    return _format_iso(datetime.now(timezone.utc))


def logical_now_iso() -> str:
    """Logical-clock UTC ISO 8601 timestamp with ms precision."""
    return _format_iso(logical_clock.now())


def _format_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    # Three fractional digits + Z suffix
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# Public alias used by other modules (orders.py, etc.)
format_iso = _format_iso


def parse_iso(value: str) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    # Accept trailing Z, optional fractional seconds.
    s = value.strip()
    if not s:
        return None
    # Replace trailing Z with +00:00 for fromisoformat
    if s.endswith("Z"):
        s2 = s[:-1] + "+00:00"
    else:
        s2 = s
    try:
        dt = datetime.fromisoformat(s2)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_iso_date(value: str) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    # YYYY-MM-DD
    try:
        d = datetime.strptime(value, "%Y-%m-%d")
        return d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def round_half_up_int(value) -> int:
    """Round half-up to nearest integer."""
    if isinstance(value, Decimal):
        d = value
    else:
        d = Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2(value) -> float:
    """Round half-up to 2 decimal places, return float."""
    if isinstance(value, Decimal):
        d = value
    else:
        d = Decimal(str(value))
    return float(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def is_int(value: Any) -> bool:
    """True for Python ints (excluding booleans)."""
    return isinstance(value, int) and not isinstance(value, bool)


def is_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    return isinstance(value, (int, float))


def is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and len(value.strip()) > 0


def utc_date_key(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%d")
