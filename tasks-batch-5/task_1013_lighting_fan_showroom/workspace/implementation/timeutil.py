"""Time / numeric helpers.

- Wall-clock UTC is used for created_at / updated_at / api_request_timestamp.
- The logical clock (in store.py) drives settled_at, confirmed_at,
  actual_ready_date, estimated_ready_date, and the trailing-365-day window.
"""
import math
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

UTC = timezone.utc


def wall_now():
    return datetime.now(UTC)


def fmt_iso(dt):
    """ISO 8601 UTC with exactly three fractional digits + 'Z'."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def wall_now_iso():
    return fmt_iso(wall_now())


def parse_iso(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Returns None if the value is not a parseable string.
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def round_half_up(value):
    """Round a numeric/Decimal value to the nearest whole integer, half-up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def floor_days(later, earlier):
    """Whole-day floor of (later - earlier)."""
    delta = later - earlier
    return math.floor(delta.total_seconds() / 86400.0)
