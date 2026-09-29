"""Low-level helpers: ids, half-up rounding, ISO 8601 formatting/parsing."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP


def new_id():
    """Server-minted UUID with no type prefix (PRD 2.4)."""
    return str(uuid.uuid4())


def _round(value, places):
    """Round half up to `places` decimals, returned as a float."""
    if value is None:
        return None
    quantum = Decimal(1).scaleb(-places)
    return float(Decimal(str(float(value))).quantize(quantum, rounding=ROUND_HALF_UP))


def r2(value):
    return _round(value, 2)


def r3(value):
    return _round(value, 3)


def r4(value):
    return _round(value, 4)


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_iso(text):
    """Parse an ISO 8601 instant; returns an aware UTC datetime or None on failure."""
    if not isinstance(text, str) or not text.strip():
        return None
    raw = text.strip()
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def days_later(dt, days):
    from datetime import timedelta
    return dt + timedelta(days=days)


def hours_later(dt, hours):
    from datetime import timedelta
    return dt + timedelta(hours=float(hours))
