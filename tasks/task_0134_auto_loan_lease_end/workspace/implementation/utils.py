"""Shared utilities: ids, timestamps, rounding, decimal helpers."""
from __future__ import annotations

import math
import secrets
import string
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, ROUND_CEILING


# ── ID helpers ──────────────────────────────────────────────────────────────


def new_uuid() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    alphabet = string.ascii_uppercase + string.ascii_lowercase + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(20))
    return f"req_{suffix}"


# ── Timestamp formatting ────────────────────────────────────────────────────


def iso_now(dt: datetime) -> str:
    """Format a UTC datetime as ISO 8601 with three fractional digits + Z.

    PRD §2.2: api_request_timestamp is ISO 8601 UTC with three fractional digits.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    ms = int(dt.microsecond / 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


# ── Rounding helpers ────────────────────────────────────────────────────────


def ceil_div(numerator: int, denominator: int) -> int:
    """Ceiling of numerator / denominator for integers (positive numerator).

    Equivalent to math.ceil(num / den) but avoids float drift.
    """
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    return -(-numerator // denominator)


def ceil_int(value) -> int:
    """Ceil a numeric value to the nearest integer using Decimal."""
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return int(d.to_integral_value(rounding=ROUND_CEILING))


def floor_int(value) -> int:
    """Floor a numeric value to the nearest integer using Decimal."""
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return int(d.to_integral_value(rounding=ROUND_FLOOR))


def round_half_up_6dp(value) -> float:
    """Round a numeric value half-up to six decimal places (returned as float).

    Used for Customer.default_rate per SCAFFOLD §1.3 customer_default_rate.
    """
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    q = d.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    return float(q)
