"""Shared utilities: timestamps, ids, ISO parsing, money rounding."""
import random
import string
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP


def new_uuid():
    """Server-minted UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def new_request_id():
    """req_ prefixed request id (PRD §2.2)."""
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def iso_z(dt):
    """ISO 8601 UTC with three fractional digits (PRD §2.4 / §2.2)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    # millisecond precision (three fractional digits), trailing Z
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value):
    """Parse an ISO 8601 instant; return tz-aware UTC datetime or raise ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def round_half_up(value):
    """Round a numeric value to a whole integer using round-half-up (away from
    zero on a .5). PRD §2.6: a value whose fractional part is exactly one-half
    rounds away from zero, upward."""
    d = Decimal(str(value)) if not isinstance(value, Decimal) else value
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
