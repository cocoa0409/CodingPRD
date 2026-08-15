"""Shared helpers: identifiers, ISO-8601 timestamps, month arithmetic."""
import uuid
from calendar import monthrange
from datetime import datetime, timezone


def new_id():
    """Server-minted resource id: bare UUID, no type prefix."""
    return str(uuid.uuid4())


def parse_iso(value):
    """Parse an ISO 8601 timestamp into an aware UTC datetime.

    Accepts a trailing 'Z' or any numeric offset. Naive timestamps are
    interpreted as UTC.
    """
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_ts(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def ts_or_none(dt):
    return fmt_ts(dt) if dt is not None else None


def add_months(dt, months):
    """Add whole calendar months, clamping the day to the target month length."""
    y = dt.year + (dt.month - 1 + months) // 12
    m = (dt.month - 1 + months) % 12 + 1
    d = min(dt.day, monthrange(y, m)[1])
    return dt.replace(year=y, month=m, day=d)
