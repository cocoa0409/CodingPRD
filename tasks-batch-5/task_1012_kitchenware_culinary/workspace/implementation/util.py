"""Time and id helpers."""
import uuid
import random
import string
from datetime import datetime, timezone

from errors import err

UTC = timezone.utc


def new_id():
    return str(uuid.uuid4())


def request_id():
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def format_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    dt = dt.astimezone(UTC)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{millis:03d}Z"


def parse_dt(value):
    """Parse an ISO-8601 string into an aware UTC datetime, else ERR_VALIDATION."""
    if not isinstance(value, str):
        raise err("ERR_VALIDATION", "invalid datetime")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise err("ERR_VALIDATION", "invalid datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def now_wall():
    return datetime.now(UTC)
