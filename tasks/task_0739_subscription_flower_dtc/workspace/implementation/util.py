"""Utilities: UUIDs, timestamps, ISO parsing, request-id, rounding."""
import uuid
import string
import random
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

ALPHANUM = string.ascii_letters + string.digits


def gen_id():
    return str(uuid.uuid4())


def gen_request_id():
    tail = "".join(random.choices(ALPHANUM, k=20))
    return f"req_{tail}"


def iso_now(dt):
    """Format a datetime as ISO8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


def parse_iso(s):
    """Parse an ISO8601 datetime, tolerating a trailing 'Z'. Returns a UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("expected ISO8601 string")
    raw = s.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except Exception as e:
        raise ValueError(f"bad iso8601: {s}") from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def round_half_up_cents(x):
    """Round a Decimal/float to nearest integer using half-up."""
    d = Decimal(str(x))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def floor_hours(delta: timedelta) -> int:
    """Floor a timedelta to whole hours (never negative from the model's POV)."""
    seconds = int(delta.total_seconds())
    if seconds < 0:
        # Age can conceivably be negative if lot was sourced in the future;
        # model treats such cases as age 0 (i.e. no shrinkage yet).
        return -((-seconds) // 3600)
    return seconds // 3600
