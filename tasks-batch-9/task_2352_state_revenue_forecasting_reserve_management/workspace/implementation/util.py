"""Pure helpers: integer-only rounding, logical-clock formatting, fiscal-year windows.

PRD §2.4: money is integer cents, every rate/ratio is integer basis points
(10000 bps = 1.0000). No float arithmetic exists anywhere in this contract, so
every division below is exact integer arithmetic with an explicit rounding mode.
"""

import re
from datetime import date, datetime, timedelta, timezone

BPS_SCALE = 10000

# PRD §2.5 — before any client sets it, the logical clock reads exactly this.
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"


# --------------------------------------------------------------------------
# Rounding (PRD §2.4)
# --------------------------------------------------------------------------
def rhu(num, den):
    """round_half_up(num / den): nearest integer, exact half away from zero."""
    if den == 0:
        return 0
    if den < 0:
        num, den = -num, -den
    if num >= 0:
        return (2 * num + den) // (2 * den)
    return -((-2 * num + den) // (2 * den))


def floor_div(num, den):
    """floor(num / den) — toward negative infinity."""
    if den == 0:
        return 0
    if den < 0:
        num, den = -num, -den
    return num // den


def ceil_div(num, den):
    """ceil(num / den) — a fractional legislative seat is a whole seat."""
    if den == 0:
        return 0
    if den < 0:
        num, den = -num, -den
    return -((-num) // den)


# --------------------------------------------------------------------------
# Timestamps
# --------------------------------------------------------------------------
_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,9}))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_dt(value):
    """Parse an ISO 8601 datetime into an aware UTC datetime. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    m = _DT_RE.match(value.strip())
    if not m:
        raise ValueError("not an ISO 8601 datetime")
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    tz = m.group(8)
    dt = datetime(year, month, day, hour, minute, second, micro, tzinfo=timezone.utc)
    if tz and tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        tz = tz[1:].replace(":", "")
        offset = timedelta(hours=int(tz[:2]), minutes=int(tz[2:4]))
        dt = dt - sign * offset
    return dt


def fmt_dt(dt):
    """Serialize a UTC datetime the way the logical clock is written."""
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03d" % (dt.microsecond // 1000) + "Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def wall_clock_stamp():
    """meta.api_request_timestamp — ISO 8601 UTC with three fractional digits."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + "%03d" % (now.microsecond // 1000) + "Z"


# --------------------------------------------------------------------------
# Dates and fiscal years (PRD §2.5)
# --------------------------------------------------------------------------
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_date_str(value):
    """Strict YYYY-MM-DD ISO date. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    m = _DATE_RE.match(value.strip())
    if not m:
        raise ValueError("not an ISO date")
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def is_date_str(value):
    try:
        parse_date_str(value)
        return True
    except ValueError:
        return False


def fy_first_day(fiscal_year):
    """Fiscal year N begins (N-1)-07-01 inclusive."""
    return date(fiscal_year - 1, 7, 1)


def fy_last_day(fiscal_year):
    """Fiscal year N ends N-06-30 (N-07-01 exclusive)."""
    return date(fiscal_year, 6, 30)


def fiscal_year_of(d):
    """The fiscal year containing calendar date d."""
    return d.year + 1 if d.month >= 7 else d.year


def month_span(start, end):
    """Whole calendar months an inclusive [start, end] overlap spans."""
    return 12 * (end.year - start.year) + (end.month - start.month) + 1
