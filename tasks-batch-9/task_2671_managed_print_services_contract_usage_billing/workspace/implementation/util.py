"""Shared primitives: datetime handling, rounding, small numeric helpers."""
import math
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

# The fixed logical-clock startup default mandated by PRD 2.4.
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

MICRO_DOLLARS_PER_CENT = 10000


def parse_dt(value):
    """Parse an ISO-8601 instant into an aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def fmt_dt(value):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.2 / 2.4)."""
    if value is None:
        return None
    dt = value.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def round_half_up(value):
    """Round a Decimal/int/Fraction-ish value half up to a whole integer."""
    if isinstance(value, Decimal):
        dec = value
    elif isinstance(value, int):
        return value
    else:
        dec = Decimal(str(value))
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2(value):
    """Round half up to two decimal places, returned as a Decimal."""
    dec = value if isinstance(value, Decimal) else Decimal(str(value))
    return dec.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def micro_to_cents(pages, rate_micro):
    """pages * rate / 10000 rounded half up to a whole cent."""
    if pages == 0 or rate_micro == 0:
        return 0
    return round_half_up(Decimal(int(pages) * int(rate_micro)) / Decimal(MICRO_DOLLARS_PER_CENT))


def ceil_hours(delta):
    """A timedelta rounded UP to a whole number of hours (never negative input)."""
    seconds = delta.total_seconds()
    if seconds <= 0:
        return 0
    return int(math.ceil(seconds / 3600.0))


def ceil_div(numerator, denominator):
    return -((-numerator) // denominator)


def add_months(dt, months):
    """Advance an instant by whole calendar months, clamping the day of month."""
    month_index = dt.month - 1 + int(months)
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    day = min(dt.day, _days_in_month(year, month))
    return dt.replace(year=year, month=month, day=day)


def _days_in_month(year, month):
    if month == 12:
        nxt = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        nxt = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return (nxt - timedelta(days=1)).day


def overlaps(a_start, a_end, b_start, b_end):
    """Half-open [start, end) intersection test; touching endpoints do not overlap."""
    return a_start < b_end and b_start < a_end
