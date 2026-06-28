"""Shared helpers: UUIDs, timestamps, parsing, rounding."""
import random
import string
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from errors import err, ERR_INVALID_REQUEST


def new_id():
    """UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def new_request_id():
    """req_-prefixed request id (PRD §2.2)."""
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def iso_now(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD §2.2 / §2.4)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso_datetime(value):
    """Parse an ISO 8601 instant into a tz-aware UTC datetime.

    Raises ERR_INVALID_REQUEST on malformed input.
    """
    if not isinstance(value, str):
        raise err(ERR_INVALID_REQUEST, "expected ISO 8601 datetime string")
    raw = value.strip()
    candidate = raw
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        raise err(ERR_INVALID_REQUEST, f"invalid datetime: {value}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def round_half_up(value):
    """Round a numeric value to the nearest integer, half away from zero.

    PRD §2.8: round-half-up (a result whose fractional part is exactly one-half
    rounds away from zero).
    """
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(value):
    """Round to 2 decimal places, half away from zero, returning a float."""
    quantized = Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(quantized)
