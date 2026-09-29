"""Server-side logical clock (PRD 2.4).

Every created_at / updated_at / *_at value, every date comparison and every
deadline evaluation is taken from this clock; the wall clock is never read.
"""
import calendar
import re
from datetime import date, datetime, timedelta, timezone

DEFAULT_NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": DEFAULT_NOW}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def now():
    return _state["now"]


def set_now(dt):
    _state["now"] = dt.astimezone(timezone.utc)


def today():
    return now().date()


def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return fmt_dt(now())


def parse_iso8601_datetime(value):
    """Parse an ISO 8601 instant.  Returns None when unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        for pattern in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(text, pattern)
                break
            except ValueError:
                continue
        else:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_iso_date(value):
    """Strict ISO 8601 calendar date (YYYY-MM-DD).  Returns None when invalid."""
    if not isinstance(value, str) or not _DATE_RE.match(value.strip()):
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def fmt_date(d):
    return None if d is None else d.isoformat()


def add_months(d, months):
    """Calendar-month arithmetic with day-of-month clamping (PRD 2.4)."""
    total = (d.year * 12 + (d.month - 1)) + months
    year, month = divmod(total, 12)
    month += 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def days_between(later, earlier):
    return (later - earlier).days


def minus_one_day(d):
    return d - timedelta(days=1)
