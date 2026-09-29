"""Exact decimal arithmetic and calendar helpers.

Money is always an integer number of cents.  Rounding is never left to the
implementation default: half-up everywhere except the two documented floors
(PRD 2.7).
"""

import calendar
import datetime
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR


def D(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def rhu(value, places=0):
    """Round half up to ``places`` decimals, returning a Decimal."""
    exp = Decimal(1).scaleb(-places)
    return D(value).quantize(exp, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def floor_int(value):
    return int(D(value).to_integral_value(rounding=ROUND_FLOOR))


def as_float(dec):
    if dec is None:
        return None
    return float(dec)


def parse_iso_date(text):
    """Strict YYYY-MM-DD."""
    if not isinstance(text, str) or len(text) != 10:
        return None
    if text[4] != "-" or text[7] != "-":
        return None
    try:
        y = int(text[0:4])
        m = int(text[5:7])
        d = int(text[8:10])
        return datetime.date(y, m, d)
    except ValueError:
        return None


def parse_iso_datetime(text):
    if not isinstance(text, str):
        return None
    raw = text.strip()
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)


def add_months(date_value, months):
    total = (date_value.year * 12 + (date_value.month - 1)) + months
    year = total // 12
    month = total % 12 + 1
    day = min(date_value.day, calendar.monthrange(year, month)[1])
    return datetime.date(year, month, day)


def day_span(start, end):
    """Whole days from start to end counting the first day."""
    return (end - start).days + 1
