"""Shared utilities: ids, timestamps, time math, rounding."""
from __future__ import annotations

import secrets
import string
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Union


# ── ID helpers ──────────────────────────────────────────────────────────────


def new_uuid() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    alphabet = string.ascii_uppercase + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(20))
    return f"req_{suffix}"


def new_access_code() -> str:
    """6-digit numeric access code (PRD §2.8)."""
    return "".join(secrets.choice(string.digits) for _ in range(6))


# ── Timestamp formatting (PRD §2.4: ISO 8601 UTC with 3 fractional digits + Z) ─


def iso_now(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    ms = int(dt.microsecond / 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


def parse_iso(value) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if not isinstance(value, str):
        raise ValueError(f"Expected datetime string, got {type(value).__name__}")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError as exc:
        raise ValueError(f"Invalid ISO datetime: {value}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ── Decimal rounding helpers ────────────────────────────────────────────────


def round_half_up_int(value: Union[Decimal, int, float, str]) -> int:
    """Round half-up to nearest whole integer."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_dec(value: Union[Decimal, int, float, str], places: int) -> Decimal:
    """Round half-up to `places` decimal places, returning Decimal."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    q = Decimal(1).scaleb(-places)  # 10^-places
    return value.quantize(q, rounding=ROUND_HALF_UP)


def to_decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal(0)
    return Decimal(str(value))


# ── Predicate helpers ───────────────────────────────────────────────────────


def is_half_step(value) -> bool:
    """True iff value is a non-negative multiple of 0.5."""
    try:
        d = Decimal(str(value))
    except Exception:
        return False
    if d < 0:
        return False
    # multiples of 0.5: 2*d must be an integer
    doubled = d * 2
    return doubled == doubled.to_integral_value()
