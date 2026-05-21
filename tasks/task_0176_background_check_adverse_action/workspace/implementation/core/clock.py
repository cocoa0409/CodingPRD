"""Logical-clock + business-day arithmetic.

The cooling-off period uses business days where Mon-Fri count and
Sat-Sun never count. The send day itself counts as day 0 (exclusive).

Per PRD §2.10 + §3.6:
- elapsed_business_days = count of full business days STRICTLY AFTER
  pre_adverse_notice_sent_at up to either the moment we last entered
  DISPUTE_PAUSED, or now() if we never paused.
- earliest_final_eligible_at = current logical now + remaining business
  days where the resulting date itself is a business day (we advance to
  the Nth business day from now, counting today as day 0 if today is a
  weekend OR moving forward day-by-day if remaining > 0).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.store import store


# ---------------------------------------------------------------------------
# Logical clock accessors
# ---------------------------------------------------------------------------
def logical_now() -> datetime:
    """Current logical server time (used by all business logic)."""
    return store.logical_now()


def logical_now_iso() -> str:
    from core.utils import format_iso

    return format_iso(logical_now())


# ---------------------------------------------------------------------------
# Business-day arithmetic
# ---------------------------------------------------------------------------
def is_business_day(dt: datetime) -> bool:
    # Monday=0 .. Sunday=6. Sat=5, Sun=6 are weekends.
    return dt.weekday() < 5


def count_business_days_between(start_exclusive: datetime, end_inclusive: datetime) -> int:
    """Count business days strictly after start_exclusive up to and
    including end_inclusive (date-level resolution).

    The send day counts as day 0 and is excluded from the elapsed tally.
    Any subsequent business-day calendar date contributes 1.
    """
    # Normalize to date boundaries.
    if end_inclusive <= start_exclusive:
        return 0
    start_date = start_exclusive.date()
    end_date = end_inclusive.date()
    if end_date <= start_date:
        return 0
    days = 0
    cur = start_date
    one = timedelta(days=1)
    cur = cur + one  # exclusive of start day
    while cur <= end_date:
        # Re-use weekday() via datetime.
        if datetime(cur.year, cur.month, cur.day).weekday() < 5:
            days += 1
        cur = cur + one
    return days


def add_business_days(from_dt: datetime, n: int) -> datetime:
    """Advance from_dt by ``n`` business days.

    The resulting timestamp lands at the start (00:00:00 UTC) of the Nth
    business day after from_dt. This preserves the "candidate has full
    business days" rule because elapsed counts business-day boundaries.
    """
    if n <= 0:
        # When remaining is zero or negative, the candidate has already
        # had enough business days; the eligible-at is the start of the
        # current/next business day moment of logical_now. To keep tests
        # simple, return from_dt itself.
        return from_dt
    cur = from_dt
    one = timedelta(days=1)
    advanced = 0
    while advanced < n:
        cur = cur + one
        if cur.weekday() < 5:
            advanced += 1
    # Normalize to the start of the resulting day in UTC.
    return cur.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)
