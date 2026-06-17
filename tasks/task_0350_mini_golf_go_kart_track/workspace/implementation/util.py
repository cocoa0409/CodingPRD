"""Shared utilities: time, ids, rounding."""
import uuid
import random
import string
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP


def new_uuid():
    return str(uuid.uuid4())


def now_iso():
    """Current wall-clock as ISO 8601 UTC with exactly 3 fractional digits."""
    return iso_format(datetime.now(timezone.utc))


def iso_format(dt):
    """Format a datetime to ISO 8601 UTC with 3 fractional digits + Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value):
    """Parse an ISO 8601 datetime string into a tz-aware UTC datetime.

    Returns None if value is None. Raises ValueError on malformed input.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse an ISO date (YYYY-MM-DD) into a date. Returns None if value None."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("not a string")
    return datetime.fromisoformat(value.strip()).date() if "T" in value or " " in value \
        else datetime.strptime(value.strip(), "%Y-%m-%d").date()


def request_id():
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def round_half_up(value):
    """Round a numeric value (int/float/Decimal) to nearest integer, half up."""
    d = Decimal(str(value)) if not isinstance(value, Decimal) else value
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
