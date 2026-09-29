"""Shared primitives: decimal arithmetic, UTC instants, identifiers."""
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, ROUND_CEILING
from datetime import date, datetime, timezone, timedelta
import uuid

UTC = timezone.utc

CENT = Decimal("1")
D2 = Decimal("0.01")
D4 = Decimal("0.0001")


def new_id():
    """Server-minted UUID with no type prefix."""
    return str(uuid.uuid4())


def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(1) if value else Decimal(0)
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def r2(value):
    return dec(value).quantize(D2, rounding=ROUND_HALF_UP)


def r4(value):
    return dec(value).quantize(D4, rounding=ROUND_HALF_UP)


def rcents(value):
    """Round half-up to a whole number of cents."""
    return int(dec(value).quantize(CENT, rounding=ROUND_HALF_UP))


def ffloor(value):
    return int(dec(value).to_integral_value(rounding=ROUND_FLOOR))


def fceil(value):
    return int(dec(value).to_integral_value(rounding=ROUND_CEILING))


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_dt(value):
    """Parse an ISO 8601 instant. Returns None when the value is not parseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_date(value):
    """Parse a calendar date. Accepts 'YYYY-MM-DD' or a full instant."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass
    parsed = parse_dt(text)
    return parsed.date() if parsed else None


def iso_date(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return "%04d-%02d-%02d" % (value.year, value.month, value.day)


def date_start(value):
    """Midnight UTC on the given calendar date (accepts date or 'YYYY-MM-DD')."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        parsed = parse_dt(value)
        if parsed is not None:
            return parsed
        value = parse_date(value)
        if value is None:
            return None
    return datetime(value.year, value.month, value.day, tzinfo=UTC)


def date_end(value):
    """The last representable millisecond of the given calendar date."""
    start = date_start(value)
    if start is None:
        return None
    return start + timedelta(days=1) - timedelta(milliseconds=1)


def shift_date(value):
    """Calendar date component of an instant."""
    return value.date() if value is not None else None


def days(n):
    return timedelta(days=n)


def minutes(n):
    return timedelta(minutes=n)


def whole_years_between(start, end, year_days="365.25"):
    """Whole years between two instants, taking 365.25 days to the year."""
    if start is None or end is None:
        return None
    elapsed = dec((end - start).total_seconds())
    year = dec(year_days) * dec(86400)
    return ffloor(elapsed / year)


def months_of_30_days(start, end):
    if start is None or end is None:
        return 0
    elapsed = dec((end - start).total_seconds())
    if elapsed < 0:
        return 0
    return ffloor(elapsed / (dec(30) * dec(86400)))


def week_anchor(instant):
    """Monday 00:00:00.000Z at or before the given instant."""
    midnight = instant.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight - timedelta(days=midnight.weekday())
