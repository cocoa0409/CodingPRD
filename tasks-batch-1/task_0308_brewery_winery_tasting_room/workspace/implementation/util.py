"""Shared helpers: id/timestamp formatting, datetime parsing, rounding."""
import random
import string
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from errors import err, ERR_INVALID_REQUEST


def new_id():
    """UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def iso_now(dt=None):
    """ISO 8601 UTC with three fractional digits (PRD §2.4)."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def request_id():
    """Server-generated request id beginning with req_ (PRD §2.2)."""
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(alphabet, k=20))


def parse_datetime(value, field="datetime"):
    """Parse an ISO 8601 instant into a tz-aware UTC datetime."""
    if not isinstance(value, str):
        raise err(ERR_INVALID_REQUEST, f"{field} must be an ISO 8601 string")
    raw = value.strip()
    try:
        s = raw
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        raise err(ERR_INVALID_REQUEST, f"{field} is not a valid ISO 8601 instant")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def round_half_up(value):
    """Round a numeric value to the nearest whole integer, half away from zero.

    PRD §2.7: mandated rounding method is round half up.
    """
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
