"""Date and time arithmetic (PRD section 2.5).

Four independent conventions live here:
  * calendar addition (days / months / years)
  * business-day counting against a pinned holiday calendar
  * 30/360 day counting with end-of-month clamping
  * interval inclusivity helpers
"""
import calendar
import re
from datetime import datetime, date, timedelta, timezone

UTC = timezone.utc

# PRD section 2.5 — the pinned holiday calendar.
HOLIDAYS = frozenset(
    [
        date(2026, 9, 7),
        date(2026, 11, 26),
        date(2026, 12, 25),
    ]
)

_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_dt(value):
    """Parse an ISO-8601 date or timestamp into an aware UTC datetime.

    Returns None when the value cannot be understood.
    """
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    if _DATE_ONLY.match(raw):
        try:
            y, m, d = (int(p) for p in raw.split("-"))
            return datetime(y, m, d, tzinfo=UTC)
        except ValueError:
            return None
    text = raw
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def is_date_only(value):
    return isinstance(value, str) and bool(_DATE_ONLY.match(value.strip()))


def iso(dt):
    """Render an aware datetime as ISO-8601 UTC with exactly 3 fractional digits."""
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def iso_date(d):
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def render_like(dt, template_raw):
    """Render dt using the same textual shape as the supplied source value."""
    if is_date_only(template_raw):
        return iso_date(dt.date())
    return iso(dt)


def add_days(dt, days):
    return dt + timedelta(days=days)


def add_months(dt, months):
    total = (dt.year * 12) + (dt.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def add_years(dt, years):
    year = dt.year + years
    day = min(dt.day, calendar.monthrange(year, dt.month)[1])
    return dt.replace(year=year, day=day)


def is_business_day(d):
    return d.weekday() < 5 and d not in HOLIDAYS


def add_business_days(start_dt, business_days):
    """Advance one calendar day at a time, counting only business days.

    The issue date itself is never counted (PRD section 2.5).
    """
    d = start_dt.astimezone(UTC).date()
    counted = 0
    guard = 0
    while counted < business_days and guard < 100000:
        d = d + timedelta(days=1)
        guard += 1
        if is_business_day(d):
            counted += 1
    return datetime(d.year, d.month, d.day, 23, 59, 59, 999000, tzinfo=UTC)


def day_count_30_360(start_dt, end_dt):
    """30/360 day count with end-of-month clamping (min(day, 30) on both ends)."""
    d1 = start_dt.astimezone(UTC).date()
    d2 = end_dt.astimezone(UTC).date()
    day1 = min(d1.day, 30)
    day2 = min(d2.day, 30)
    return (d2.year - d1.year) * 360 + (d2.month - d1.month) * 30 + (day2 - day1)


def whole_days_between(from_dt, to_dt):
    return (to_dt.astimezone(UTC).date() - from_dt.astimezone(UTC).date()).days


def wall_now():
    return datetime.now(tz=UTC)


def wall_now_iso():
    return iso(wall_now())
