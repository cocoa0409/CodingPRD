"""Shared utilities: ID/timestamp formatting, ISO parsing."""
import uuid
import random
import string
from datetime import datetime, timezone, timedelta


def new_uuid():
    return str(uuid.uuid4())


def iso_format(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(alphabet, k=20))


def parse_iso(value):
    """Parse an ISO 8601 instant into an aware UTC datetime, or None on failure."""
    if value is None or not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse a YYYY-MM-DD date string into a date, or None on failure."""
    if value is None or not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def add_minutes(dt, minutes):
    return dt + timedelta(minutes=minutes)


def add_days(dt, days):
    return dt + timedelta(days=days)
