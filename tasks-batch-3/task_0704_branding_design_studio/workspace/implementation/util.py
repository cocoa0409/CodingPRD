"""Shared utilities: ids, timestamps, ISO 8601 parsing, money rounding."""
import uuid
import random
import string
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP


def new_id():
    """System-generated id formatted as a UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def new_request_id():
    """Server-generated unique request id that starts with req_ (PRD §2.2)."""
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def iso_now(dt):
    """ISO 8601 UTC timestamp with exactly three fractional digits (PRD §2.4)."""
    dt = dt.astimezone(timezone.utc)
    # millisecond precision, trailing Z
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso8601(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Returns None when the value is not a parseable ISO 8601 datetime string.
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def round_half_up(value):
    """Round a numeric value to a whole integer using round-half-up.

    A value exactly halfway between two whole cents rounds to the larger
    magnitude (PRD §2.5).
    """
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def mul_round_half_up(cents, fraction):
    """round_half_up(cents * fraction) using Decimal for exactness."""
    result = Decimal(str(cents)) * Decimal(str(fraction))
    return int(result.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
