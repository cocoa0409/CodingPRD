"""Time, id, and validation helpers for the Immigrant Welcome Center API."""
import re
import uuid
import random
import string
from datetime import datetime, timezone, date

from errors import ApiError


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

class LogicalClock:
    """Server-maintained logical clock; never falls back to wall-clock time."""

    DEFAULT = "2026-08-01T00:00:00Z"

    def __init__(self):
        self._now = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt
        return self._now


CLOCK = LogicalClock()


# ---------------------------------------------------------------------------
# Time parsing / formatting
# ---------------------------------------------------------------------------

def fmt_iso(dt):
    """Canonical ISO-8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


def parse_iso(value):
    """Parse an ISO-8601 datetime string into an aware UTC datetime.

    Accepts a trailing Z or a numeric offset, with or without fractional
    seconds. Raises ApiError(400) on garbage.
    """
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "expected an ISO-8601 datetime string")
    v = value.strip()
    try:
        if v.endswith("Z") or v.endswith("z"):
            v = v[:-1] + "+00:00"
        dt = datetime.fromisoformat(v)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       f"malformed datetime: {value!r}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(value, field):
    """Validate a YYYY-MM-DD date string; returns the original string."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       f"{field} must be a YYYY-MM-DD date")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       f"{field} must be a valid calendar date")
    return value


def date_as_dt(datestr):
    return datetime.strptime(datestr, "%Y-%m-%d").replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Ids
# ---------------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


def new_request_id():
    rand = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + rand


# ---------------------------------------------------------------------------
# Request-body field validators (structural, rung 7)
# ---------------------------------------------------------------------------

def body_json():
    """Return the request JSON body as a dict, or raise 400."""
    from flask import request
    if not request.data:
        return {}
    data = request.get_json(force=True, silent=True)
    if data is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "request body must be JSON")
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "request body must be a JSON object")
    return data


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_present(data, field):
    if field not in data or data[field] is None:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       f"missing required field: {field}")
    return data[field]


def req_str(data, field):
    v = req_present(data, field)
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       f"{field} must be a string")
    return v


def opt_str(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       f"{field} must be a string")
    return v


def req_int(data, field, minimum=None):
    v = req_present(data, field)
    if not is_int(v):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       f"{field} must be an integer")
    if minimum is not None and v < minimum:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       f"{field} must be >= {minimum}")
    return v


def opt_int(data, field, default=None, minimum=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not is_int(v):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       f"{field} must be an integer")
    if minimum is not None and v < minimum:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       f"{field} must be >= {minimum}")
    return v


def req_enum(data, field, allowed):
    v = req_present(data, field)
    if v not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       f"{field} must be one of {sorted(allowed)}")
    return v


def req_datetime(data, field):
    v = req_present(data, field)
    return parse_iso(v)


def opt_datetime(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    return parse_iso(data[field])
