"""Shared helpers: id/timestamp generation, ISO8601 parse/format, money rounding."""
import random
import string
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

import clock
from errors import ApiError, ERR_INVALID_REQUEST


def new_uuid():
    return str(uuid.uuid4())


def new_request_id():
    chars = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(chars, k=20))


def iso_format(dt):
    """ISO 8601 UTC with three fractional digits (milliseconds)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return iso_format(clock.now())


def parse_iso(value):
    """Parse an ISO 8601 UTC instant. Raise ERR_INVALID_REQUEST on failure.

    Returns a timezone-aware datetime in UTC.
    """
    if not isinstance(value, str):
        raise ApiError(*ERR_INVALID_REQUEST, message="Invalid timestamp")
    s = value.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError(*ERR_INVALID_REQUEST, message="Invalid timestamp format")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def round_half_up(frac):
    """Round an exact rational (Fraction) to the nearest integer, half up."""
    d = Decimal(frac.numerator) / Decimal(frac.denominator)
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def to_fraction(value):
    return Fraction(value)
