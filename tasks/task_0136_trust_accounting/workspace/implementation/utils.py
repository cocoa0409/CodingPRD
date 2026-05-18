"""Shared utilities: IDs, ISO 8601 timestamps, decimal math, rounding."""
from __future__ import annotations

import secrets
import string
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP


# ── ID helpers ──────────────────────────────────────────────────────────────


def new_uuid() -> str:
    """Server-minted UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def new_request_id() -> str:
    """`req_` + 20 char alphanumeric for api_request_id (PRD §2.2)."""
    alphabet = string.ascii_uppercase + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(20))
    return f"req_{suffix}"


# ── Timestamp formatting (PRD §2.4: ISO 8601 UTC, 3 fractional digits) ──────


def iso_now(dt: datetime) -> str:
    """Format a datetime as ISO 8601 UTC with three fractional digits + Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    ms = int(dt.microsecond / 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


def parse_iso(value):
    """Parse an ISO 8601 string into a UTC-aware datetime."""
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


# ── Decimal/money helpers (PRD §2.7: 2dp, ROUND_HALF_UP) ────────────────────

TWO_PLACES = Decimal("0.01")


def to_decimal(value) -> Decimal:
    """Convert a JSON number/string to Decimal without float-mediation losses."""
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        # bool is a subclass of int — reject it explicitly upstream; here treat as 0/1.
        return Decimal(int(value))
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        # Avoid the binary-float round-trip by going through repr → str.
        return Decimal(repr(value))
    if isinstance(value, str):
        return Decimal(value)
    raise ValueError(f"Cannot convert {type(value).__name__} to Decimal")


def money(value) -> Decimal:
    """Round a value to 2 decimal places using ROUND_HALF_UP."""
    return to_decimal(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def money_float(value) -> float:
    """Express a money Decimal as a JSON float (2dp)."""
    return float(money(value))
