"""Time, rounding, and freight-class helpers."""
import math
import re
from datetime import datetime, timedelta, timezone, date, time as dtime
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING, ROUND_FLOOR
from fractions import Fraction
from zoneinfo import ZoneInfo

from errors import err_invalid_request

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Datetime formatting / parsing
# ---------------------------------------------------------------------------
def fmt_ts(dt):
    """Entity timestamp: ISO 8601 UTC with three fractional digits (PRD §2.4)."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_clock(dt):
    """Clock echo: seconds precision when whole, else three fractional digits."""
    dt = dt.astimezone(UTC)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return fmt_ts(dt)


def fmt_date_as_ts(d):
    """A calendar date rendered as a datetime at midnight UTC."""
    if d is None:
        return None
    return fmt_ts(datetime(d.year, d.month, d.day, tzinfo=UTC))


def parse_datetime(value, field="datetime"):
    """Parse an ISO 8601 datetime (accepts trailing Z, offsets, date-only)."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        s = value.strip()
        try:
            if s.endswith("Z") or s.endswith("z"):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)
        except ValueError:
            # try date-only
            try:
                d = date.fromisoformat(value.strip())
                dt = datetime(d.year, d.month, d.day)
            except ValueError:
                raise err_invalid_request(f"Field '{field}' must be an ISO 8601 datetime.")
    else:
        raise err_invalid_request(f"Field '{field}' must be an ISO 8601 datetime string.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


# ---------------------------------------------------------------------------
# Business days (skip Saturdays and Sundays; the start date counts as day 0)
# ---------------------------------------------------------------------------
def business_days_after_date(d, n):
    d = d if isinstance(d, date) and not isinstance(d, datetime) else d.date()
    remaining = int(n)
    while remaining > 0:
        d = d + timedelta(days=1)
        if d.weekday() < 5:
            remaining -= 1
    return d


def business_days_after_dt(dt, n):
    new_date = business_days_after_date(dt.date(), n)
    return datetime.combine(new_date, dt.time(), tzinfo=UTC)


def next_business_day(d):
    return business_days_after_date(d, 1)


# ---------------------------------------------------------------------------
# Numbers / rounding
# ---------------------------------------------------------------------------
def to_decimal(value):
    """Exact Decimal from a JSON number (int/float/str)."""
    if isinstance(value, bool):
        raise err_invalid_request("Boolean is not a valid number.")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, str):
        try:
            return Decimal(value)
        except Exception:
            raise err_invalid_request(f"Invalid numeric value: {value!r}.")
    if isinstance(value, Decimal):
        return value
    raise err_invalid_request(f"Invalid numeric value: {value!r}.")


def to_fraction(value):
    return Fraction(to_decimal(value))


def ceil_fraction(fr):
    return -(-fr.numerator // fr.denominator)


def round_half_up_int(dec):
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool))


# ---------------------------------------------------------------------------
# Freight classification (PRD §2.10): intervals (lower, upper]
# ---------------------------------------------------------------------------
FREIGHT_CLASS_TABLE = [
    ("50",  Decimal("50")),
    ("55",  Decimal("35")),
    ("60",  Decimal("30")),
    ("65",  Decimal("22.5")),
    ("70",  Decimal("18")),
    ("77.5", Decimal("15")),
    ("85",  Decimal("13.5")),
    ("92.5", Decimal("12")),
    ("100", Decimal("10.5")),
    ("110", Decimal("9")),
    ("125", Decimal("8")),
    ("150", Decimal("7")),
    ("175", Decimal("6")),
    ("200", Decimal("5")),
    ("250", Decimal("4")),
    ("300", Decimal("3")),
    ("400", Decimal("2")),
]

RATE_CENTS_PER_LB = {
    "50": 90, "55": 105, "60": 120, "65": 120, "70": 120, "77.5": 120,
    "85": 120, "92.5": 120, "100": 145, "110": 145, "125": 145,
    "150": 175, "175": 175, "200": 175, "250": 210, "300": 210,
    "400": 210, "500": 210,
}


def freight_class_for_density(density_value):
    """Return the NMFC class string, or None when density < 1 (unratable)."""
    d = to_decimal(density_value)
    for cls, lower in FREIGHT_CLASS_TABLE:
        if d > lower:
            return cls
    if d >= Decimal("1"):
        return "500"
    return None


def class_numeric(cls):
    return Decimal(cls)


_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def valid_hhmm(s):
    return isinstance(s, str) and bool(_HHMM.match(s))


def valid_timezone(tz):
    if not isinstance(tz, str) or not tz:
        return False
    try:
        ZoneInfo(tz)
        return True
    except Exception:
        return False
