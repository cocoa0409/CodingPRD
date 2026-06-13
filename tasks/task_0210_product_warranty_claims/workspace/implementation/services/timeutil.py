"""Date / time utilities.

All timestamps in the domain are ISO 8601 UTC. The PRD speaks of "whole months"
(floored) for elapsed-age computations and of "purchase_date + N months" for
warranty_end_date. We implement both with calendar-aware month arithmetic.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


def parse_iso(s: str) -> datetime:
    """Parse an ISO 8601 string into a timezone-aware UTC datetime.

    Accepts a trailing 'Z' or an explicit offset. Naive inputs are treated as UTC.
    """
    if not isinstance(s, str):
        raise ValueError("not a string")
    txt = s.strip()
    if txt.endswith("Z") or txt.endswith("z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_months(dt: datetime, months: int) -> datetime:
    """Return dt advanced by `months` calendar months (clamping day-of-month)."""
    total = (dt.year * 12 + (dt.month - 1)) + months
    year = total // 12
    month = total % 12 + 1
    # clamp day to last valid day of the target month
    day = dt.day
    last = _days_in_month(year, month)
    if day > last:
        day = last
    return dt.replace(year=year, month=month, day=day)


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        nxt = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        nxt = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    first = datetime(year, month, 1, tzinfo=timezone.utc)
    return (nxt - first).days


def whole_months_between(start: datetime, end: datetime) -> int:
    """Number of complete (floored) calendar months from start to end.

    A complete month is counted only once `end` has reached or passed the
    same day-and-time-of-month as `start`. If `end` precedes `start` the
    result is 0 (never negative) — elapsed age is clamped at zero.
    """
    if end <= start:
        return 0
    months = (end.year - start.year) * 12 + (end.month - start.month)
    # The anchor is start advanced by `months`. If that anchor is still after
    # end, we have not completed the last month -> step back one.
    if months > 0:
        anchor = add_months(start, months)
        if anchor > end:
            months -= 1
    elif months == 0:
        # same calendar month; end > start but < 1 month elapsed
        return 0
    return max(0, months)
