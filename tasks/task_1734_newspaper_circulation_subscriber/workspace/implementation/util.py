"""Date/time and rounding helpers. All money is integer cents; every
fractional application is rounded HALF-UP at the point stated by the calc."""
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def D(x):
    return Decimal(str(x))


def rhu(x):
    """Round half-up to the nearest integer cent."""
    return int(D(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def parse_date(s):
    """Strict YYYY-MM-DD -> date, or None."""
    if not isinstance(s, str) or not _DATE_RE.match(s):
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def parse_dt(s):
    """ISO 8601 -> aware datetime (naive treated as UTC), or None."""
    if not isinstance(s, str):
        return None
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-08-01T00:00:00.000Z."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


def fmt_clock(dt):
    """Render a logical-clock instant the way the clock itself reads (PRD 2.5:
    the clock starts at exactly 2026-08-01T00:00:00Z). Fractional digits appear
    only when the stamped instant actually carries them."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    if dt.microsecond:
        base += f".{dt.microsecond // 1000:03d}"
    return base + "Z"


def fmt_date(d):
    return d.isoformat() if d is not None else None


def days(n):
    return timedelta(days=n)
