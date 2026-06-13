"""Monetary helpers — integer cents, round-half-up, clock arithmetic."""
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal


def round_half_up_div(numerator, denominator):
    """round_half_up(numerator / denominator) to a whole integer.

    numerator/denominator are integers; returns an int.
    """
    q = (Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(q)


def parse_iso(ts):
    """Parse an ISO 8601 UTC timestamp (with optional fractional seconds / Z)."""
    s = ts.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso_millis(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def subtract_days(ts, days):
    """Return ISO string of ts minus `days` calendar days."""
    dt = parse_iso(ts)
    return format_iso_millis(dt - timedelta(days=days))


def days_between_floor(now_ts, future_ts):
    """floor((future - now) / 86400 seconds) — whole 86400-second days."""
    now = parse_iso(now_ts)
    future = parse_iso(future_ts)
    delta_seconds = (future - now).total_seconds()
    import math

    return math.floor(delta_seconds / 86400.0)
