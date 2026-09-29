"""Datetime / numeric helpers with the rounding discipline of PRD 2.6."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP


def parse_iso(value):
    """Parse an ISO 8601 UTC instant. Raises ValueError on anything else."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if not s:
        raise ValueError("empty")
    if s[-1] in ("Z", "z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_decimal(value):
    """Coerce a JSON scalar to Decimal without float contamination."""
    if isinstance(value, bool):
        raise ValueError("bool is not a number")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, str):
        s = value.strip()
        if not s:
            raise ValueError("empty")
        return Decimal(s)
    if isinstance(value, Decimal):
        return value
    raise ValueError("not a number")


def round_half_up(value):
    """Round to a whole unit, half away from zero."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_1dp(value):
    return Decimal(value).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def num(value):
    """Serialise a Decimal/number for JSON."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value
