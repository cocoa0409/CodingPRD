"""Date/time helpers operating against the logical clock.

All date fields are YYYY-MM-DD strings; all instants ISO 8601 UTC.
Calendar-month arithmetic preserves day-of-month, clamped to month length.
"""

from datetime import date, datetime, timedelta, timezone
import calendar

from db import store


def parse_date(s: str) -> date:
    """Parse YYYY-MM-DD, raising ValueError on malformed input."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    parts = s.split("-")
    if len(parts) != 3:
        raise ValueError("bad date")
    y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
    return date(y, m, d)


def format_date(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def add_months(d: date, months: int) -> date:
    """Add calendar months preserving day-of-month, clamped to month length."""
    total = (d.year * 12 + (d.month - 1)) + months
    y = total // 12
    m = total % 12 + 1
    last = calendar.monthrange(y, m)[1]
    day = min(d.day, last)
    return date(y, m, day)


def clock_date() -> date:
    """Current logical clock date (UTC date portion)."""
    iso = store.clock_iso
    # Accept forms like 2026-05-01T00:00:00Z or with fractional seconds
    return parse_instant(iso).date()


def clock_iso() -> str:
    return store.clock_iso


def parse_instant(s: str) -> datetime:
    """Parse ISO 8601 instant to aware datetime (UTC assumed on Z suffix)."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_instant(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def month_key(d: date):
    """(year, month) tuple usable for month bucket comparisons."""
    return (d.year, d.month)


def month_of_date_str(s: str):
    return month_key(parse_date(s))


def add_days(d: date, days: int) -> date:
    return d + timedelta(days=days)


def quarter_key(d: date):
    return (d.year, (d.month - 1) // 3)
