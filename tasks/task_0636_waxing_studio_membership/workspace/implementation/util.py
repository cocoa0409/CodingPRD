"""Shared helpers: id/timestamp minting, datetime parsing/formatting, rounding."""
import uuid
import random
import string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from errors import err


def new_id():
    # PRD 2.4: server-minted id is a UUID with no type prefix.
    return str(uuid.uuid4())


def new_request_id():
    # PRD 2.2: api_request_id is server-generated and starts with "req_".
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    """Parse an ISO 8601 instant; raise ERR_INVALID_REQUEST on bad input."""
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", "invalid datetime")
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "invalid datetime: %s" % value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def round_half_up(value):
    """Round a fractional value to a whole integer using round-half-up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def minute_of_day(dt):
    """Time-of-day in whole minutes after 00:00 UTC for the given instant."""
    dt = dt.astimezone(timezone.utc)
    return dt.hour * 60 + dt.minute


def add_days(dt, days):
    return dt + timedelta(days=days)


def add_minutes(dt, minutes):
    return dt + timedelta(minutes=minutes)
