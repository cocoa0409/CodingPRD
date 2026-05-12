"""Banking-day arithmetic. Mon-Fri count, Sat/Sun skipped, no holidays."""

from datetime import datetime, timedelta, timezone


def banking_days_between(start: datetime, end: datetime) -> int:
    """Count banking days strictly greater than start.date() up to and including end.date(),
    where banking days are Mon..Fri (weekday 0..4). Holidays not modeled.
    Returns 0 when end <= start.
    """
    if end is None or start is None:
        return 0
    if end <= start:
        return 0
    s = start.date()
    e = end.date()
    if e == s:
        return 0
    count = 0
    d = s + timedelta(days=1)
    while d <= e:
        if d.weekday() < 5:
            count += 1
        d += timedelta(days=1)
    return count


def add_banking_days(start: datetime, n: int) -> datetime:
    """Return a UTC datetime that is n banking days after start (count Mon-Fri only)."""
    if start is None:
        return None
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    cur = start
    added = 0
    while added < n:
        cur = cur + timedelta(days=1)
        if cur.weekday() < 5:
            added += 1
    return cur
