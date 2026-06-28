"""Shared helpers: timestamps, ids, datetime parsing, rounding."""
import uuid
import random
import string
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

from errors import invalid_request


def new_id():
    """Server-minted UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def request_id():
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def iso_now(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD §2.2/§2.4)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso8601(value, field="datetime"):
    """Parse an ISO 8601 UTC datetime string into a timezone-aware datetime."""
    if not isinstance(value, str):
        raise invalid_request(f"{field} must be an ISO 8601 string")
    raw = value.strip()
    try:
        s = raw
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        raise invalid_request(f"{field} is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def round_half_up_2dp(value):
    """Round a numeric value half-up to 2 decimal places, return float."""
    d = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    # Normalize to a plain float for JSON output.
    return float(d)


def round_half_up_int(value):
    """Round a Decimal/number half-up to an integer."""
    d = Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(d)


def floor_int(value):
    d = Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_FLOOR)
    return int(d)
