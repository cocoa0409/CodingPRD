"""Timestamp / date helpers bound to the logical clock and ISO formats."""
import calendar as _cal
import random
import string
from datetime import datetime, timedelta, timezone, date

from store import clock, clock_date


def iso3(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    """created_at / updated_at stamped from the logical clock."""
    return iso3(clock())


def request_timestamp():
    """meta.api_request_timestamp -- wall clock, three fractional digits."""
    return iso3(datetime.now(timezone.utc))


def request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def parse_datetime(s):
    """Parse an ISO 8601 datetime (Z or numeric offset). Returns aware UTC dt or None."""
    if not isinstance(s, str):
        return None
    txt = s.strip()
    try:
        if txt.endswith("Z"):
            dt = datetime.fromisoformat(txt[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(txt)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def parse_date(s):
    """Parse a strict YYYY-MM-DD date. Returns date or None."""
    if not isinstance(s, str):
        return None
    try:
        dt = datetime.strptime(s.strip(), "%Y-%m-%d")
        return dt.date()
    except (ValueError, OverflowError):
        return None


def calendar_months(bd, ref):
    """Whole calendar months between birthdate bd and reference date ref.

    A month completes on the same day-of-month as the birthdate, clamped to
    the month end when the target month is shorter.
    """
    months = (ref.year - bd.year) * 12 + (ref.month - bd.month)
    dim = _cal.monthrange(ref.year, ref.month)[1]
    if ref.day < min(bd.day, dim):
        months -= 1
    return months


def stage_for(months):
    if months < 12:
        return "INFANT"
    if months < 36:
        return "TODDLER"
    if months < 60:
        return "PRESCHOOLER"
    return "EARLY_SCHOOL"


def whole_days(a, b):
    """Floor of (b - a) in whole days."""
    return (b - a).days
