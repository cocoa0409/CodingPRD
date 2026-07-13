"""Time, money and rounding helpers.

Money is integer cents everywhere.  Percentages are applied with Decimal and
rounded HALF_UP exactly once, at exactly the point the PRD names.
"""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits, 'Z' suffix."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    """Wall-clock stamp used only for the request envelope and record bookkeeping
    (created_at / updated_at).  Every *domain* deadline uses the logical clock."""
    return iso(datetime.now(timezone.utc))


def parse_dt(value):
    """Parse an ISO 8601 instant.  Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def rhu(value):
    """Round HALF_UP to a whole cent / whole unit."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def floor_int(value):
    """Truncate toward zero (values here are never negative)."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.to_integral_value(rounding=ROUND_FLOOR))


def dec(value):
    return Decimal(str(value))
