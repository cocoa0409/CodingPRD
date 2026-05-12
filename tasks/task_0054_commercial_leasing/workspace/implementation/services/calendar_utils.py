"""Calendar helpers: month iteration, day counting, half-open interval math."""
from datetime import datetime, timezone, timedelta
import calendar as _cal


def add_months(dt: datetime, months: int) -> datetime:
    """Return dt + months, anchored at the same day-of-month (clamped to last day)."""
    y = dt.year + (dt.month - 1 + months) // 12
    m = (dt.month - 1 + months) % 12 + 1
    last_day = _cal.monthrange(y, m)[1]
    d = min(dt.day, last_day)
    return dt.replace(year=y, month=m, day=d)


def first_of_month(dt: datetime) -> datetime:
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def first_of_next_month(dt: datetime) -> datetime:
    return add_months(first_of_month(dt), 1)


def days_in_month(year: int, month: int) -> int:
    return _cal.monthrange(year, month)[1]


def iter_months(start: datetime, end: datetime):
    """Yield tuples (period_start, period_end) of calendar months that overlap [start, end)."""
    cur = first_of_month(start)
    while cur < end:
        nxt = first_of_next_month(cur)
        yield cur, nxt
        cur = nxt


def half_open_overlap(a_start: datetime, a_end: datetime,
                      b_start: datetime, b_end: datetime) -> bool:
    """Half-open intervals [a_start, a_end) and [b_start, b_end) overlap?"""
    return a_start < b_end and b_start < a_end


def closed_interval_overlap_half_open(closed_start: datetime, closed_end: datetime,
                                      ho_start: datetime, ho_end: datetime) -> bool:
    """[closed_start, closed_end] overlaps [ho_start, ho_end)?

    Closed includes its end; half-open excludes. Overlap iff there exists x where
    closed_start <= x <= closed_end AND ho_start <= x < ho_end.
    Equivalent to: closed_start < ho_end AND ho_start <= closed_end.
    """
    return closed_start < ho_end and ho_start <= closed_end


def months_between(start: datetime, end: datetime) -> int:
    """Number of whole calendar months between [start, end), assuming both align to 1st-of-month."""
    if start >= end:
        return 0
    return (end.year - start.year) * 12 + (end.month - start.month)


def intersect_days(a_start: datetime, a_end: datetime,
                   b_start: datetime, b_end: datetime) -> int:
    """Count of full days in the intersection of two half-open intervals."""
    lo = max(a_start, b_start)
    hi = min(a_end, b_end)
    if lo >= hi:
        return 0
    return (hi - lo).days
