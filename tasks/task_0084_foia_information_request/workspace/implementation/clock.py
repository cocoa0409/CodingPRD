"""Server clock + datetime helpers.

The test-driving clock (PRD §3.10) lets tests set the server's notion of
"now" via POST /_clock/set_current_utc {to_iso8601}. All timestamp-producing
code (envelope timestamps, system fields, deadline-outcome comparisons,
appeal-window and reverse-notice arithmetic) reads through here so that
deadline/appeal/reverse arithmetic can be exercised deterministically.

State lives in module globals; the store starts with a real wall-clock "now"
on every fresh boot (no seeding of business entities — this is just the clock).
"""

from datetime import datetime, timedelta, timezone

# When None, "now" tracks the real wall clock. When set, "now" is frozen to the
# supplied instant (test-driving). Reset on every process boot.
_frozen_now = None


def set_now(dt):
    """Freeze the server clock to a timezone-aware UTC datetime."""
    global _frozen_now
    _frozen_now = dt


def now() -> datetime:
    if _frozen_now is not None:
        return _frozen_now
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return to_iso(now())


def to_iso(dt: datetime) -> str:
    """ISO 8601 UTC with exactly three fractional digits and trailing Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value):
    """Parse an ISO 8601 instant into a tz-aware UTC datetime, or None on failure."""
    if not isinstance(value, str) or not value:
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---- Working-day arithmetic (PRD §2.8) -------------------------------------
# A working day is any day that is not Saturday or Sunday. weekday(): Mon=0..Sun=6.
_WEEKEND = {5, 6}


def add_working_days(start: datetime, n: int) -> datetime:
    """Advance `start` calendar-day by calendar-day, counting only non-weekend
    days, until n such days have been counted. n may be 0 (returns start)."""
    d = start
    added = 0
    while added < n:
        d = d + timedelta(days=1)
        if d.weekday() not in _WEEKEND:
            added += 1
    return d


def working_days_between(open_dt: datetime, close_dt: datetime) -> int:
    """Count working days strictly between an open and a close instant, counting
    the open day but not the close day (PRD §3.5 tolling-window rule).

    Concretely: number of distinct calendar days d with
    open.date() <= d < close.date() that are not weekends.
    """
    if close_dt <= open_dt:
        return 0
    start_date = open_dt.date()
    end_date = close_dt.date()
    count = 0
    d = start_date
    while d < end_date:
        if d.weekday() not in _WEEKEND:
            count += 1
        d = d + timedelta(days=1)
    return count


def end_of_working_day(dt: datetime) -> datetime:
    """Fix a computed deadline to the final instant of its working day:
    23:59:59.999Z (PRD §2.8)."""
    return dt.replace(hour=23, minute=59, second=59, microsecond=999000, tzinfo=timezone.utc)
