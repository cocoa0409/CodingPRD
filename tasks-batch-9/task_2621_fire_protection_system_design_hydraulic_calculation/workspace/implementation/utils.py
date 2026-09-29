"""Numeric and datetime helpers.

Every rounding operation in the specification is ROUND HALF UP on the decimal
value (PRD 2.6): a digit sequence exactly at the midpoint rounds away from
zero.  There is no banker's rounding anywhere in the service.
"""
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING, ROUND_FLOOR


def _dec(x):
    if isinstance(x, Decimal):
        return x
    if isinstance(x, int):
        return Decimal(x)
    return Decimal(repr(float(x)))


def rhu(x, places):
    """Round half up to `places` decimal places, returning a float."""
    q = Decimal(1).scaleb(-int(places))
    return float(_dec(x).quantize(q, rounding=ROUND_HALF_UP))


def ceil_div_steps(numerator, step):
    """ceil(numerator / step) as an exact integer number of steps."""
    q = _dec(numerator) / _dec(step)
    return int(q.to_integral_value(rounding=ROUND_CEILING))


def floor_div_steps(numerator, step):
    """floor(numerator / step) as an exact integer number of steps."""
    q = _dec(numerator) / _dec(step)
    return int(q.to_integral_value(rounding=ROUND_FLOOR))


ISO_FMT = "%Y-%m-%dT%H:%M:%S.%f"


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime(ISO_FMT)[:-3] + "Z"


def parse_dt(value):
    """Parse an ISO 8601 datetime string.  Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def days(n):
    return timedelta(days=n)


def minutes(n):
    return timedelta(minutes=n)
