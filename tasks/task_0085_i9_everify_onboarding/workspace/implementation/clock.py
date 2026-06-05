"""Deterministic logical server clock plus time / business-day arithmetic.

PRD §2.6: the server runs against a deterministic logical clock that a
ComplianceOfficer sets explicitly via POST /_clock/set_current_utc. Wherever the
PRD says "the clock," it means this value. Until set, the clock falls back to
real wall-clock UTC so that timestamps are still sensible.

All timestamps are ISO 8601 UTC with three fractional digits.
"""

from datetime import datetime, timezone, timedelta

# PRD §2.6 / SCAFFOLD section2_deadline.constants — fixed 2026 federal holidays.
FEDERAL_HOLIDAYS = {
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-05-25", "2026-06-19",
    "2026-07-03", "2026-09-07", "2026-11-11", "2026-11-26", "2026-12-25",
}


class Clock:
    """Holds the deterministic 'current' instant. None => use wall clock."""

    def __init__(self):
        self._current = None

    def set(self, dt):
        self._current = dt

    def now(self):
        if self._current is not None:
            return self._current
        return datetime.now(timezone.utc)

    def reset(self):
        self._current = None


clock = Clock()


def now():
    return clock.now()


def parse_iso8601(value):
    """Parse an ISO 8601 string into an aware UTC datetime. Returns None for
    None. Raises ValueError on malformed input (caller maps to ERR_INVALID_*)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    if not isinstance(value, str):
        raise ValueError("not a datetime string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso8601(dt):
    """Format an aware datetime as ISO 8601 UTC with exactly three fractional
    digits and a trailing Z, per PRD §2.4 / §2.6."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(dt.microsecond / 1000):03d}Z"


def is_business_day(d):
    """d is a date. Business day excludes Sat/Sun and the 2026 federal
    holidays (PRD §2.6)."""
    if d.weekday() >= 5:  # 5 = Saturday, 6 = Sunday
        return False
    if d.isoformat() in FEDERAL_HOLIDAYS:
        return False
    return True


def section2_deadline_from_hire_date(hire_date):
    """PRD §3.2 / SCAFFOLD section2_deadline.

    Starting from the calendar date of hire_date at 00:00:00Z, walk forward one
    calendar day at a time; each day that is a business day counts as one
    business day. The first business day strictly after hire_date is day one;
    the hire date itself never counts. Stop once three business days have been
    counted. The third counted business day, stamped at 23:59:59.999Z, is the
    section2_deadline.
    """
    d = hire_date.astimezone(timezone.utc).date()
    counted = 0
    while counted < 3:
        d = d + timedelta(days=1)
        if is_business_day(d):
            counted += 1
    return datetime(d.year, d.month, d.day, 23, 59, 59, 999000, tzinfo=timezone.utc)


def add_gov_business_days(anchor, n):
    """Add n federal-government business days to an anchor datetime, used for the
    TNC referral_deadline (PRD §3.4: tnc_issued_at + 10 federal-government
    business days). Same weekend+holiday business-day set. Counting begins the
    first business day after the anchor date; deadline stamped at 23:59:59.999Z
    of the resolved day."""
    d = anchor.astimezone(timezone.utc).date()
    counted = 0
    while counted < n:
        d = d + timedelta(days=1)
        if is_business_day(d):
            counted += 1
    return datetime(d.year, d.month, d.day, 23, 59, 59, 999000, tzinfo=timezone.utc)


def add_calendar_days(anchor, n):
    """Add n calendar days to a datetime (used for the receipt 90-day window and
    STEM cap-gap whole-day arithmetic)."""
    return anchor + timedelta(days=n)
