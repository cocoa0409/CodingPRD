"""Shared utilities: UUID, time, decimal helpers."""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP


def new_id() -> str:
    """Return a UUID-v4 string with no prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def now_utc() -> datetime:
    """Wall-clock now in UTC (used only for system-managed metadata like created_at/updated_at).

    Note: business-logic timestamps use the SystemClock singleton; see services/clock.py.
    """
    return datetime.now(timezone.utc)


def to_iso_millis(dt: datetime) -> str:
    """ISO 8601 UTC with exactly 3 fractional digits (PRD §2.4)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{millis:03d}Z"


def parse_iso(text):
    """Parse a flexible ISO 8601 string to a UTC datetime; returns None on failure."""
    if text is None:
        return None
    if isinstance(text, datetime):
        return text if text.tzinfo else text.replace(tzinfo=timezone.utc)
    if not isinstance(text, str) or not text:
        return None
    s = text.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def round_half_up(value, places: int = 0) -> Decimal:
    """Decimal ROUND_HALF_UP to `places` decimal places."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    if places <= 0:
        quant = Decimal("1")
    else:
        quant = Decimal("1").scaleb(-places)
    return value.quantize(quant, rounding=ROUND_HALF_UP)


def round_half_up_int(value) -> int:
    """ROUND_HALF_UP to a whole number, returned as int."""
    return int(round_half_up(value, 0))


def add_days(dt: datetime, days: int) -> datetime:
    """Add calendar days to a datetime, preserving UTC tz."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt + timedelta(days=days)


def end_of_day_utc(dt: datetime) -> datetime:
    """Return dt at 23:59:59.999 UTC (preserves date)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.replace(hour=23, minute=59, second=59, microsecond=999000)


def start_of_day_utc(dt: datetime) -> datetime:
    """Return dt at 00:00:00.000 UTC (preserves date)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)
