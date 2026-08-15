"""Datetime / decimal / id helpers."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from errors import ERR_VALIDATION, raise_err


def now_utc():
    """Wall-clock instant used for audit timestamps (created_at/updated_at)."""
    return datetime.now(timezone.utc)


def ts_audit(dt):
    """Audit timestamp format: ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def ts_domain(dt):
    """Domain datetime format: ISO 8601 UTC; fractional digits only when present."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_dt(value, field="datetime"):
    """Parse an ISO 8601 datetime string (Z or offset); naive values treated as UTC."""
    if not isinstance(value, str) or not value.strip():
        raise_err(ERR_VALIDATION, "field '%s' must be an ISO 8601 datetime string" % field)
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise_err(ERR_VALIDATION, "field '%s' must be an ISO 8601 datetime string" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def new_id():
    return str(uuid.uuid4())


def dec(value):
    """Convert a JSON number to Decimal exactly (via str, never via binary float)."""
    return Decimal(str(value))


def cents(value):
    """Round a Decimal monetary amount half-up to integer cents."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round1(value):
    """Round a Decimal half-up to one decimal place."""
    return value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def whole_days(start, end):
    """Whole (24h) days contained in the half-open interval [start, end)."""
    if end <= start:
        return 0
    return int((end - start).total_seconds() // 86400)


def num_out(value):
    """Serialize a Decimal (or None) as a JSON number."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value
