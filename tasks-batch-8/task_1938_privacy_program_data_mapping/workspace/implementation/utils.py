"""Time, decimal, and type helpers."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP


def parse_ts(value):
    """Parse an ISO 8601 timestamp to an aware UTC datetime.

    Raises ValueError on any malformed input.
    """
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g.
    2026-08-01T00:00:00.000Z."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def add_days(dt, days):
    return dt + timedelta(days=days)


def round_half_up_int(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)
