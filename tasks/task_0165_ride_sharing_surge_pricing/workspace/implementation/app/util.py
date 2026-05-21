"""Utility helpers — IDs, timestamps, rounding."""
from __future__ import annotations

import secrets
import string
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

_ALPHANUM = string.ascii_letters + string.digits


def new_uuid() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    body = "".join(secrets.choice(_ALPHANUM) for _ in range(20))
    return f"req_{body}"


def format_iso8601(dt: datetime) -> str:
    """ISO 8601 UTC with three fractional digits and trailing Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    millis = f"{dt.microsecond // 1000:03d}"
    return f"{base}.{millis}Z"


def parse_iso8601(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def round_half_up_int(value) -> int:
    """Round a numeric value half-up to integer cents."""
    if isinstance(value, Decimal):
        d = value
    elif isinstance(value, int):
        return int(value)
    else:
        d = Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_decimal(value, places: int) -> Decimal:
    """Round to N decimal places half-up; returns a Decimal."""
    if isinstance(value, Decimal):
        d = value
    else:
        d = Decimal(str(value))
    q = Decimal("1").scaleb(-places)  # 10^-places
    return d.quantize(q, rounding=ROUND_HALF_UP)


def decimal_2dp_to_float(d: Decimal) -> float:
    """Convert a 2-dp Decimal to a JSON-friendly float."""
    return float(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
