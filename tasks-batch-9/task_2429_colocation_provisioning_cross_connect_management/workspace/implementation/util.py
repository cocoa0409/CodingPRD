"""Timestamps, the logical clock format and decimal helpers.

PRD §2.4 — every timestamp is ISO 8601 UTC with three fractional digits.
PRD §2.7 — all rounding is half-up; the number of decimals is fixed per kind
of quantity (kW/kWh 3, money 2, unit rate 4, percentage 1).
"""

import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

UTC = timezone.utc

# PRD §2.4 — "Until it is set for the first time, the clock reads 2026-08-01T00:00:00Z."
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)


def new_id():
    """PRD §2.4 — id is a UUID with no type prefix."""
    return str(uuid.uuid4())


def new_request_id():
    """PRD §2.2 — api_request_id starts with req_."""
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def parse_dt(value):
    """Parse an ISO-8601 UTC datetime. Returns None when the value is not a
    well-formed ISO-8601 datetime string."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s or ("T" not in s and "t" not in s):
        return None
    if s[-1] in ("Z", "z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if not isinstance(dt, datetime):
        return dt
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def wall_now():
    return datetime.now(tz=UTC)


# --------------------------------------------------------------------------
# Decimal helpers — never use float arithmetic for money or capacity figures.
# --------------------------------------------------------------------------

def dec(value):
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def _q(value, places):
    exp = Decimal(1).scaleb(-places)
    return dec(value).quantize(exp, rounding=ROUND_HALF_UP)


def q1(value):
    return float(_q(value, 1))


def q2(value):
    return float(_q(value, 2))


def q3(value):
    return float(_q(value, 3))


def q4(value):
    return float(_q(value, 4))


def dsum(values):
    total = Decimal("0")
    for v in values:
        total += dec(v)
    return total


def floor_div(value, divisor):
    """Whole quotient rounded down (the bundle budget of PRD §3.6)."""
    quotient = dec(value) / dec(divisor)
    return int(quotient.to_integral_value(rounding=ROUND_FLOOR))


def ceil_div(value, divisor):
    """Whole quotient rounded up (a labour increment of PRD §3.6)."""
    quotient = dec(value) / dec(divisor)
    return int(quotient.to_integral_value(rounding=ROUND_CEILING))


def days_ago(clock, days):
    return clock - timedelta(days=days)
