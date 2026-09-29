"""Time helpers.

Every domain instant in this API comes from the server's logical clock (PRD 2.4);
nothing here reads wall-clock time except `wall_now_iso`, which is only used for
the response envelope's `api_request_timestamp`.
"""
import re
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone

_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d+)?(?:(Z|z)|([+-])(\d{2}):?(\d{2}))$"
)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_instant(value):
    """Parse an ISO 8601 UTC instant. Returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    m = _INSTANT_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute, second = (int(m.group(i)) for i in range(1, 7))
    frac = m.group(7)
    micro = 0
    if frac:
        digits = (frac[1:] + "000000")[:6]
        micro = int(digits)
    try:
        dt = datetime(year, month, day, hour, minute, second, micro, tzinfo=timezone.utc)
    except ValueError:
        return None
    if m.group(9):
        sign = 1 if m.group(9) == "+" else -1
        offset = timedelta(hours=int(m.group(10)), minutes=int(m.group(11)))
        dt = dt - sign * offset
    return dt


def parse_date(value):
    """Parse a YYYY-MM-DD calendar date. Returns a date or None."""
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def fmt_instant(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


def fmt_domain_instant(dt):
    """A logical-clock instant, rendered exactly as PRD 2.4 / 3.4 render them.

    The clock is set to an operator-supplied `current_utc` and the domain stamps
    that read it are reported back at that instant's own precision: PRD 2.4 says
    the unset clock "reads exactly 2026-08-01T00:00:00Z" and PRD 3.4 pins
    "A hold placed at 2026-09-01T00:00:00Z ... expires at 2028-03-02T00:00:00Z".
    Only `created_at`, `updated_at` and `api_request_timestamp` are specified to
    carry three fractional digits, and those keep using `fmt_instant`.
    """
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return "%04d-%02d-%02dT%02d:%02d:%02dZ" % (
            dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        )
    return fmt_instant(dt)


def fmt_date(d):
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def wall_now_iso():
    return fmt_instant(datetime.now(timezone.utc))


def add_days(dt, days):
    """Whole-day arithmetic on a UTC instant; the time-of-day rides along (PRD 3.4)."""
    return dt + timedelta(days=int(days))


def day_span(later, earlier):
    """Whole calendar days between two dates (half-open counting)."""
    return (later - earlier).days


def midnight(d):
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def add_years_months(d, years, months):
    """Calendar arithmetic used for the 59.5-year 1099-R threshold (PRD 3.9 step 7)."""
    total = d.month - 1 + months
    year = d.year + years + total // 12
    month = total % 12 + 1
    day = min(d.day, monthrange(year, month)[1])
    return date(year, month, day)
