"""Shared utilities: ids, timestamps, datetime parsing, decimal rounding."""
import random
import string
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP


def new_id():
    """Server-minted UUID with no type prefix (PRD §2.5)."""
    return str(uuid.uuid4())


def new_request_id():
    """A server-generated request id starting with req_ (PRD §2.2)."""
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def iso_now_ms():
    """ISO 8601 UTC timestamp with three fractional digits (PRD §2.5, §2.2)."""
    return iso_format(datetime.now(timezone.utc))


def iso_format(dt):
    """Format a tz-aware datetime as ISO 8601 UTC with three fractional digits.

    e.g. 2025-05-24T10:30:00.123Z
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_datetime(value):
    """Parse an ISO 8601 datetime/date string into a tz-aware UTC datetime.

    Returns None if not parseable. Accepts trailing 'Z', explicit offsets, and
    bare dates (treated as midnight UTC).
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    candidate = s
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        # Try a plain date
        try:
            dt = datetime.strptime(s, "%Y-%m-%d")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def round_money(value, places=2):
    """Round-half-up to a fixed number of decimal places, returned as float."""
    d = Decimal(str(value)).quantize(Decimal("1." + "0" * places) if places > 0 else Decimal("1"),
                                     rounding=ROUND_HALF_UP)
    return float(d)


def round2(value):
    return round_money(value, 2)


def round1(value):
    return round_money(value, 1)


def add_hours(dt, hours):
    return dt + timedelta(hours=hours)


def add_days(dt, days):
    return dt + timedelta(days=days)
