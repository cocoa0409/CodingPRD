"""Shared low-level helpers: id generation, request-id, timestamp formatting,
datetime parsing (PRD §2.2 / §2.4 / §3.6)."""
import random
import string
import uuid
from datetime import datetime, timezone


def new_id():
    """Server-minted id: a bare UUID4 string with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def new_request_id():
    """meta.api_request_id: a random alphanumeric string starting with 'req_'
    (PRD §2.2)."""
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def iso(dt):
    """Format a datetime as ISO 8601 UTC with three fractional digits and a 'Z'
    suffix, e.g. 2025-05-24T10:30:00.123Z (PRD §2.2 / §2.4)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + (".%03dZ" % ms)


def parse_dt(value):
    """Parse an ISO 8601 datetime string into a timezone-aware UTC datetime.

    Returns None if the value is not a parseable datetime string.
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    candidate = s
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                dt = datetime.strptime(s, fmt)
                break
            except ValueError:
                continue
        else:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
