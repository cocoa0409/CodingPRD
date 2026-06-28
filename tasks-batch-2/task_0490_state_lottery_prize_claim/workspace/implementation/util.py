"""Shared helpers: timestamps, ISO datetime parsing, money rounding, request ids."""
import random
import string
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from errors import err


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def format_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits, 'Z' suffix."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    else:
        dt = dt.replace(tzinfo=timezone.utc)
    # millisecond precision
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_ts(clock_value):
    """For meta.api_request_timestamp: wall-clock independent — use real UTC now."""
    return format_ts(datetime.now(timezone.utc))


def parse_iso8601(value, field="datetime"):
    """Parse an ISO 8601 string into a timezone-aware UTC datetime."""
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", f"{field} must be an ISO 8601 string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", f"{field} is not a valid ISO 8601 instant")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def round_half_up(amount):
    """Round a Decimal/number to the nearest whole cent (integer) using half-up."""
    d = Decimal(str(amount)) if not isinstance(amount, Decimal) else amount
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def mul_round(base_cents, rate):
    """base_cents (int) * rate (number) rounded half-up to whole cents."""
    product = Decimal(int(base_cents)) * Decimal(str(rate))
    return int(product.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def add_days(dt, days):
    return dt + timedelta(days=days)
