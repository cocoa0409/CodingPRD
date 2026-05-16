"""Date arithmetic helpers."""

from datetime import date, datetime, timedelta, timezone


def parse_iso_date(s: str) -> date:
    """Parse a YYYY-MM-DD date string."""
    return datetime.strptime(s, "%Y-%m-%d").date()


def to_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return parse_iso_date(value)


def first_of_month(d: date) -> date:
    return date(d.year, d.month, 1)


def first_day_of_next_month(d: date) -> date:
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


def last_day_of_month(d: date) -> date:
    nxt = first_day_of_next_month(d)
    return nxt - timedelta(days=1)


def years_between(birth: date, ref: date) -> int:
    """Return the age in years between birth and ref (whole years)."""
    years = ref.year - birth.year
    if (ref.month, ref.day) < (birth.month, birth.day):
        years -= 1
    return years


def add_days(d: date, n: int) -> date:
    return d + timedelta(days=n)


def parse_iso_datetime(s: str) -> datetime:
    """Parse an ISO datetime string with optional Z timezone."""
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def iso_date_str(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def yyyy_mm(d: date) -> str:
    return d.strftime("%Y-%m")


def parse_yyyy_mm(s: str) -> date:
    """Parse YYYY-MM and return first-of-month date."""
    return datetime.strptime(s + "-01", "%Y-%m-%d").date()
