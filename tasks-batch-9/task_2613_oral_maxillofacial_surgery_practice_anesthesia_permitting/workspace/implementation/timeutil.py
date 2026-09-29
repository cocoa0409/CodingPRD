"""Temporal helpers.

All domain timestamps are ISO 8601 UTC strings with exactly three fractional
digits and a trailing 'Z' (PRD 2.4).  Operator-supplied instants are echoed back
verbatim as received; server-computed instants are rendered with fmt_dt().
"""
import calendar
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(\.\d+)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_dt(value):
    """Parse an ISO-8601 instant into an aware UTC datetime; None when unusable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    m = _ISO_RE.match(text)
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7)
    micro = 0
    if frac:
        digits = (frac[1:] + "000000")[:6]
        micro = int(digits)
    offset = m.group(8)
    try:
        naive = datetime(year, month, day, hour, minute, second, micro)
    except ValueError:
        return None
    if offset in (None, "Z", "z"):
        return naive.replace(tzinfo=timezone.utc)
    sign = 1 if offset[0] == "+" else -1
    body = offset[1:].replace(":", "")
    delta = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
    return (naive - sign * delta).replace(tzinfo=timezone.utc)


def parse_date(value):
    """Parse a calendar date (or full instant) into an aware UTC datetime."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", text):
        try:
            return datetime(int(text[0:4]), int(text[5:7]), int(text[8:10]), tzinfo=timezone.utc)
        except ValueError:
            return None
    return parse_dt(text)


def fmt_dt(dt):
    """Render an aware datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


def now_real():
    return datetime.now(timezone.utc)


def _clamp_day(year, month, day):
    last = calendar.monthrange(year, month)[1]
    return min(day, last)


def add_months(dt, months):
    """Calendar-month addition; a day-of-month with no counterpart clamps down."""
    total = (dt.year * 12 + (dt.month - 1)) + months
    year, month = divmod(total, 12)
    month += 1
    day = _clamp_day(year, month, dt.day)
    return dt.replace(year=year, month=month, day=day)


def add_years(dt, years):
    """Calendar-year addition; 29 February clamps to 28 February."""
    return add_months(dt, years * 12)


def whole_minutes(start, end):
    """Whole minutes elapsed from start to end (truncated toward minus infinity)."""
    seconds = (end - start).total_seconds()
    return int(seconds // 60)


def whole_years(start, end):
    """Whole years elapsed from start to end, floored on the anniversary."""
    years = end.year - start.year
    if years and add_years(start, years) > end:
        years -= 1
    while years >= 0 and add_years(start, years) > end:
        years -= 1
    return years


def r2(value):
    """Round a Decimal to two places, half up."""
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def rcents(value):
    """Round a Decimal to whole integer cents, half up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dec(value):
    """Lossless Decimal from a JSON number (never via binary float)."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def num2(value):
    """Serialise a two-place Decimal as a JSON number."""
    return float(r2(value))
