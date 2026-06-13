"""Shared utilities: id minting, timestamp formatting, datetime parsing, rounding."""
import uuid
import random
import string
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def iso_now_3():
    """Real-wall-clock UTC ISO8601 with exactly three fractional digits, Z suffix."""
    return iso_format(datetime.now(timezone.utc))


def iso_format(dt):
    """Format a datetime as ISO8601 UTC with three fractional digits, Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    # millisecond precision
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def parse_iso(s):
    """Parse an ISO8601 datetime string to an aware UTC datetime. Returns None on failure."""
    if not isinstance(s, str):
        return None
    text = s.strip()
    if not text:
        return None
    # Normalize trailing Z to +00:00 for fromisoformat
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def round_half_up(value):
    """Round a numeric value to the nearest integer using round-half-up. Returns int."""
    d = Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
