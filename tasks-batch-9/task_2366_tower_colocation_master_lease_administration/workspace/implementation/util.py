"""Numeric, decimal and temporal helpers.

All money is integer cents.  All rounding is round-half-up unless a rule
explicitly says otherwise (cost-share allocation floors).  Load units and
percentages carry three decimal places, round half up (PRD 2.10).
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, getcontext
import calendar

getcontext().prec = 60

ZERO = Decimal(0)


def dec(value):
    """Coerce an int/float/str/Decimal into a Decimal without binary noise."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise TypeError("bool is not a number")
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def rhu(value, places=0):
    """Round half up to `places` decimal places."""
    q = Decimal(1).scaleb(-places)
    return dec(value).quantize(q, rounding=ROUND_HALF_UP)


def rhu_cents(value):
    """Round half up to whole cents, returned as int."""
    return int(rhu(value, 0))


def rhu3(value):
    """Round half up to three decimal places (load units / percentages)."""
    return rhu(value, 3)


def floor_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_FLOOR))


def num(value):
    """JSON-friendly rendering of a numeric value.

    Integral values render as ints, everything else as floats.  Both compare
    equal to the corresponding Python literal, so callers can assert either.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    d = dec(value)
    if d == d.to_integral_value():
        return int(d)
    return float(d)


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------

def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_dt(raw):
    """Parse an ISO 8601 instant (or a bare calendar date) into aware UTC.

    Returns None when the value cannot be parsed.
    """
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.strptime(text, "%Y-%m-%d")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def add_years(dt, years):
    """Same month/day one or more years later; 29 Feb collapses to 28 Feb."""
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:
        return dt.replace(year=dt.year + years, day=28)


def anniversary_count(base, as_of, cap=4000):
    """Number of integers k >= 1 such that base + k years <= as_of."""
    if base is None or as_of is None:
        return 0
    count = 0
    k = 1
    while k <= cap:
        if add_years(base, k) <= as_of:
            count = k
            k += 1
        else:
            break
    return count


def add_days(dt, days):
    return dt + timedelta(days=days)


def last_day_of_month(year, month):
    return calendar.monthrange(year, month)[1]


def is_first_of_month(dt):
    return dt.day == 1


def is_last_of_month(dt):
    return dt.day == last_day_of_month(dt.year, dt.month)


def month_starts_within(start, end, cap=4000):
    """First-day instants of every calendar month fully inside [start, end].

    The interval is inclusive on both ends and both bounds are instants; a
    month counts when its first day is at or after `start` and its last day is
    at or before `end` (dates compared, not instants).
    """
    if start is None or end is None:
        return []
    out = []
    year, month = start.year, start.month
    guard = 0
    while guard < cap:
        guard += 1
        first = datetime(year, month, 1, tzinfo=timezone.utc)
        last = datetime(year, month, last_day_of_month(year, month),
                        23, 59, 59, 999000, tzinfo=timezone.utc)
        if first.date() > end.date():
            break
        if first.date() >= start.date() and last.date() <= end.date():
            out.append(first)
        month += 1
        if month == 13:
            month = 1
            year += 1
    return out
