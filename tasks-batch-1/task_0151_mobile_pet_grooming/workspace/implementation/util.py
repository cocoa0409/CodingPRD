"""Shared utilities: id/timestamp formatting, datetime parsing."""
import uuid
import random
import string
from datetime import datetime, timezone

from errors import err, ERR_INVALID_REQUEST


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def iso(dt):
    """Render an aware datetime as ISO 8601 UTC with exactly 3 fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    # millisecond precision, trailing Z
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value, field_name="timestamp"):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Raises ERR_INVALID_REQUEST on a malformed value.
    """
    if not isinstance(value, str):
        raise err(ERR_INVALID_REQUEST, f"{field_name} must be an ISO 8601 string")
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        raise err(ERR_INVALID_REQUEST, f"{field_name} is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
