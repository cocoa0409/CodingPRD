"""Shared helpers: ids, timestamps, calendar arithmetic, serialization."""
import calendar
import random
import string
import uuid
from datetime import date, datetime, timezone


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def parse_iso_datetime(value):
    """Parse an ISO 8601 datetime to an aware UTC datetime at second precision.

    Returns None when the value is not a valid datetime string.
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    try:
        if s.endswith("Z") or s.endswith("z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    # Time comparisons are made at second precision (PRD 2.4)
    return dt.astimezone(timezone.utc).replace(microsecond=0)


def parse_iso_date(value):
    """Parse an ISO 8601 date (YYYY-MM-DD). Returns None when invalid."""
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def fmt_ts(dt: datetime) -> str:
    """ISO 8601 UTC timestamp with three fractional digits (PRD 2.5)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def add_months(d: date, months: int) -> date:
    """Calendrical month addition with end-of-month clamping."""
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    day = min(d.day, calendar.monthrange(y, m)[1])
    return date(y, m, day)


def months_elapsed(closing: date, today: date, cap: int = 120) -> int:
    """Number of monthly anniversaries of `closing` on or before `today` (capped)."""
    m = 0
    while m < cap and add_months(closing, m + 1) <= today:
        m += 1
    return m


def serialize(entity: dict) -> dict:
    """Public view of a stored entity: datetimes/dates to ISO strings, internals stripped."""
    out = {}
    for k, v in entity.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = fmt_ts(v)
        elif isinstance(v, date):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out
