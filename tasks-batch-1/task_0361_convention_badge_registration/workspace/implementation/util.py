"""Shared utilities: id/timestamp minting, time formatting/parsing, rounding."""
import uuid
import random
import string
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

import clock


def new_id():
    """Server-minted id formatted as a UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def iso_now():
    """Current server clock as ISO 8601 UTC with three fractional digits."""
    return format_iso(clock.now())


def format_iso(dt):
    """Format a timezone-aware datetime as ISO 8601 UTC with milliseconds + Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value):
    """Parse an ISO 8601 string into a timezone-aware UTC datetime.

    Returns None if the value is not a parseable datetime string.
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    # Normalize trailing Z to +00:00 for fromisoformat
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def request_id():
    """Server-generated unique request id beginning with 'req_' (PRD §2.2)."""
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def round_half_up(value):
    """Round a numeric value half-up to the nearest whole integer (cents)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
