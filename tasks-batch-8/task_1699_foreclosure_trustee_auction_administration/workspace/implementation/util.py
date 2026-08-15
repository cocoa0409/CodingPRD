"""Date / datetime / decimal helpers.

Date arithmetic is in whole calendar days (PRD §2.6). Where a day count is
taken between two dates, the start date is excluded and the end date is
included — i.e. days = (to_date - from_date).days.
"""
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date_strict(value):
    """Parse a strict YYYY-MM-DD date string into a datetime.date, or None."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def format_date(d):
    if d is None:
        return None
    if isinstance(d, datetime):
        d = d.date()
    return d.strftime("%Y-%m-%d")


def add_days(d, n):
    """date + n days -> date."""
    return d + timedelta(days=n)


def add_days_dt(dt, n):
    """datetime + n days -> datetime."""
    return dt + timedelta(days=n)


def day_count(from_date, to_date):
    """Calendar days from `from_date` (excluded) through `to_date` (included).
    Negative windows are clamped to zero (defensive; clock can move backward)."""
    days = (to_date - from_date).days
    return days if days > 0 else 0


def business_days_before(d, n):
    """The date n business days before d: walk backward one calendar day at a
    time counting only Mon-Fri (weekends skipped; no holiday calendar)."""
    cur = d
    counted = 0
    while counted < n:
        cur = cur - timedelta(days=1)
        if cur.weekday() < 5:  # Mon=0 .. Fri=4
            counted += 1
    return cur


def rhu(value):
    """Round a Decimal half-up to whole cents -> int."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dec_rate(rate):
    """Convert a JSON numeric note_rate_pct to Decimal exactly."""
    return Decimal(str(rate))


def iso_to_datestr(iso_dt_str):
    """Extract the YYYY-MM-DD calendar date of a normalized ISO datetime string."""
    from db import _parse_iso
    return format_date(_parse_iso(iso_dt_str).date())


_FRAC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z$")


def format_like(reference_str, dt):
    """Render dt (aware UTC) in the same style as reference_str: plain
    'YYYY-MM-DDTHH:MM:SSZ' when the reference has no fractional part,
    otherwise ISO8601 with three fractional digits. Used for computed
    datetimes derived from caller-supplied instants (stay auto-postpone)."""
    from db import _format_iso
    dt = dt.astimezone(timezone.utc)
    if isinstance(reference_str, str) and reference_str.endswith("Z") and not _FRAC_RE.match(reference_str):
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return _format_iso(dt)
