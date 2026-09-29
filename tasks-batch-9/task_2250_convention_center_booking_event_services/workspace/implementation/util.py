"""Date, interval and timestamp helpers (PRD 2.4, 2.5, 2.7).

This module deliberately has no knowledge of the data store so it can be
imported from anywhere.
"""

import calendar
import re
from datetime import date, datetime, timedelta, timezone

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# --------------------------------------------------------------------------
# timestamps
# --------------------------------------------------------------------------
def iso_instant(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-08-01T00:00:00.000Z."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def parse_instant(text):
    """Parse an ISO 8601 instant.  Returns None when unparseable."""
    if not isinstance(text, str):
        return None
    raw = text.strip()
    if not raw:
        return None
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def midnight(day):
    """The instant 00:00:00.000Z of a calendar date."""
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# calendar dates
# --------------------------------------------------------------------------
def parse_date(text):
    """Parse a strict YYYY-MM-DD calendar date.  Returns None when invalid."""
    if not isinstance(text, str) or not DATE_RE.match(text):
        return None
    try:
        return date(int(text[0:4]), int(text[5:7]), int(text[8:10]))
    except ValueError:
        return None


def date_diff_days(later, earlier):
    """Plain difference in calendar days (later - earlier)."""
    return (later - earlier).days


def inclusive_days(start, end):
    """Day count over the closed interval [start, end]."""
    return (end - start).days + 1


def shift_months(day, months):
    """Move a calendar date by whole months, clamping the day of month."""
    total = (day.year * 12 + (day.month - 1)) + months
    year, month = divmod(total, 12)
    month += 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last))


def whole_months_between(start, end):
    """Whole months from `start` forward to `end` (negative when end < start)."""
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return months


def add_days(day, n):
    return day + timedelta(days=n)


# --------------------------------------------------------------------------
# closed interval arithmetic (PRD 2.7)
# --------------------------------------------------------------------------
def intervals_intersect(a_start, a_end, b_start, b_end):
    """Closed intervals intersect when a shared endpoint counts."""
    return a_start <= b_end and b_start <= a_end


def clears_buffered_window(cand_start, cand_end, win_start, win_end, buffer_days):
    """True when the candidate interval clears the buffered maintenance window.

    The buffered window extends `buffer_days` days before window_start_date and
    `buffer_days` days after window_end_date; clearing means not intersecting it,
    so separation of exactly buffer_days is NOT enough.
    """
    buffered_start = add_days(win_start, -buffer_days)
    buffered_end = add_days(win_end, buffer_days)
    return not intervals_intersect(cand_start, cand_end, buffered_start, buffered_end)
