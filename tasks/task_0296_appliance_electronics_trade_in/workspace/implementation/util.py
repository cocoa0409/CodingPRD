"""Shared utilities: timestamp formatting, ISO parsing, money rounding."""
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from errors import err, ERR_INVALID_REQUEST


def new_id():
    """Server-minted UUID with no type prefix (PRD 2.6)."""
    return str(uuid.uuid4())


def iso_now(dt):
    """Format a datetime as ISO 8601 UTC with exactly three fractional digits.

    e.g. 2025-05-24T10:30:00.123Z
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    # millisecond precision, three fractional digits, trailing Z
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Accepts a trailing 'Z' or an explicit offset. Raises ERR_INVALID_REQUEST
    on malformed input.
    """
    if not isinstance(value, str):
        raise err(ERR_INVALID_REQUEST, "expected an ISO 8601 datetime string")
    raw = value.strip()
    candidate = raw
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        raise err(ERR_INVALID_REQUEST, f"invalid datetime: {value}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def round_half_up(value):
    """Round a Decimal/number to the nearest integer, half-up. Returns int."""
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def mult_round_half_up(cents, fraction):
    """Multiply integer cents by a fractional factor, round half-up to int cents."""
    product = Decimal(int(cents)) * Decimal(str(fraction))
    return round_half_up(product)


def add_hours(dt, hours):
    return dt + timedelta(hours=int(hours))
