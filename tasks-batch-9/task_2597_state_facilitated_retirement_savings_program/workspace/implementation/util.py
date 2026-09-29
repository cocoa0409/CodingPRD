"""Shared low-level helpers: ids, rounding, date and instant arithmetic.

Every monetary quantity in this service is an integer count of cents and every
rate is an integer count of basis points (10000 bp == the whole).  All
divisions by 10000 round half up (away from zero) as PRD 2.6 requires.
"""
import random
import string
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

TOTAL_BP = 10000


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def round_half_up(value):
    """Round a Decimal/int/Fraction-ish value to the nearest integer, halves away from zero."""
    if not isinstance(value, Decimal):
        value = Decimal(value)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def bp_of(amount_cents, bp):
    """round_half_up(amount * bp / 10000) with no intermediate rounding."""
    return round_half_up(Decimal(int(amount_cents)) * Decimal(int(bp)) / Decimal(TOTAL_BP))


def mul_div_round(numer_a, numer_b, denom):
    """round_half_up(a * b / denom)."""
    return round_half_up(Decimal(int(numer_a)) * Decimal(int(numer_b)) / Decimal(int(denom)))


# ---------------------------------------------------------------- date & time

def fmt_instant(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-08-01T00:00:00.000Z"""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_date(d):
    if d is None:
        return None
    if isinstance(d, str):
        return d
    return d.isoformat()


def parse_date(value):
    """Strict ISO calendar date (YYYY-MM-DD).  Returns a date or None when invalid."""
    if not isinstance(value, str):
        return None
    if len(value) != 10 or value[4] != "-" or value[7] != "-":
        return None
    try:
        return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except (ValueError, TypeError):
        return None


def parse_instant(value):
    """Accept an ISO 8601 instant, with or without a trailing Z / offset / fraction."""
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        # Allow a bare calendar date as an instant at midnight.
        d = parse_date(value)
        if d is None:
            return None
        return datetime(d.year, d.month, d.day)
    if dt.tzinfo is not None:
        dt = (dt - dt.utcoffset()).replace(tzinfo=None)
    return dt


def add_days(d, days):
    return d + timedelta(days=int(days))


def days_between(start, end):
    """Whole days from start to end (may be negative)."""
    return (end - start).days


def add_years(d, years):
    """Same month/day in d.year + years; 29 February degrades to 28 February."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(year=d.year + years, day=28)


def month_day_in_year(month_day, year):
    """Build a date from an "MM-DD" string inside the given year."""
    try:
        month = int(month_day[0:2])
        day = int(month_day[3:5])
        return date(year, month, day)
    except (ValueError, TypeError, IndexError):
        return date(year, 4, 15)


def ceil_div(numer, denom):
    numer = int(numer)
    denom = int(denom)
    if numer <= 0:
        return 0
    return -((-numer) // denom)
