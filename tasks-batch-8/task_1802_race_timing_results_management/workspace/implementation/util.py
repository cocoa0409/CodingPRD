"""Datetime / numeric helpers."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP


def parse_dt(value):
    """Parse an ISO 8601 datetime into an aware UTC datetime; None on failure."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse a strict YYYY-MM-DD date; None on failure."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if len(s) != 10 or s[4] != "-" or s[7] != "-":
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return (
        f"{dt.year:04d}-{dt.month:02d}-{dt.day:02d}T"
        f"{dt.hour:02d}:{dt.minute:02d}:{dt.second:02d}."
        f"{dt.microsecond // 1000:03d}Z"
    )


def ms_between(earlier, later):
    """Exact integer milliseconds between two datetimes (round-half-up if not ms-aligned)."""
    delta = later - earlier
    micros = delta.days * 86400_000_000 + delta.seconds * 1_000_000 + delta.microseconds
    return int((Decimal(micros) / Decimal(1000)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu(value):
    """Round half up to the nearest integer."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def fmt_km(x):
    """Compact rendering of a km distance for the timing config fingerprint."""
    if isinstance(x, bool):
        return str(x)
    if isinstance(x, float) and x.is_integer():
        return str(int(x))
    return str(x)
