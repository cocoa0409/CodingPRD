"""Time / clock / arithmetic helpers.

The logical clock is the ONLY source of "now" for business rules (PRD 2.4).
Nothing in the domain reads the host clock.
"""
import calendar
import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

CLOCK_DEFAULT_UTC = "2026-08-01T00:00:00Z"

_state = {"now": None}


def _fmt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def iso(dt):
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    return _fmt(dt)


def parse_dt(value):
    """Parse an ISO-8601 instant. Returns None when unparseable."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if not isinstance(value, str):
        return None
    txt = value.strip()
    if not txt:
        return None
    if txt.endswith("Z") or txt.endswith("z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date_only(value):
    """Parse a plain calendar date (YYYY-MM-DD) or a full instant."""
    if value is None or not isinstance(value, str):
        return parse_dt(value)
    txt = value.strip()
    if len(txt) == 10:
        try:
            d = datetime.strptime(txt, "%Y-%m-%d")
        except ValueError:
            return None
        return d.replace(tzinfo=timezone.utc)
    return parse_dt(txt)


def reset_clock():
    _state["now"] = parse_dt(CLOCK_DEFAULT_UTC)


def set_clock(dt):
    _state["now"] = dt


def now_dt():
    if _state["now"] is None:
        reset_clock()
    return _state["now"]


def now_iso():
    return iso(now_dt())


def wall_iso():
    return _fmt(datetime.now(timezone.utc))


def add_days(dt, days):
    return dt + timedelta(days=days)


def add_minutes(dt, minutes):
    return dt + timedelta(minutes=minutes)


def _last_day(year, month):
    return calendar.monthrange(year, month)[1]


def add_months(dt, months):
    total = (dt.year * 12 + (dt.month - 1)) + months
    year = total // 12
    month = total % 12 + 1
    day = min(dt.day, _last_day(year, month))
    return dt.replace(year=year, month=month, day=day)


def whole_months_between(start, end):
    """Number of whole calendar months from start to end (floor, may be negative)."""
    if start is None or end is None:
        return 0
    months = (end.year - start.year) * 12 + (end.month - start.month)
    anchor = add_months(start, months)
    if anchor > end:
        months -= 1
    return months


def first_of_next_month(dt):
    """UTC midnight of the first day of the month AFTER dt."""
    total = dt.year * 12 + (dt.month - 1) + 1
    year = total // 12
    month = total % 12 + 1
    return datetime(year, month, 1, tzinfo=timezone.utc)


def ceil_div(numerator, denominator):
    if denominator == 0:
        return 0
    return -((-numerator) // denominator)


def floor_to_increment(minutes, increment):
    return (int(minutes) // increment) * increment


def round_half_up(value, places):
    quant = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quant, rounding=ROUND_HALF_UP)


def days_between_ceil(later, earlier):
    """Whole days, rounding up any partial day."""
    delta = later - earlier
    seconds = delta.total_seconds()
    if seconds <= 0:
        return 0
    return int(math.ceil(seconds / 86400.0))
