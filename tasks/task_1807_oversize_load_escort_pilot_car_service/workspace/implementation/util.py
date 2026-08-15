"""Time, parsing, and field-validation helpers."""

import re
import uuid
from datetime import datetime, timezone

from errors import ERR_INVALID_REQUEST, ERR_INVALID_ENUM_VALUE, raise_err


def new_id():
    return str(uuid.uuid4())


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-08-01T00:00:00.000Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    """Parse an ISO 8601 datetime; returns None when unparsable."""
    if not isinstance(value, str):
        return None
    t = value.strip()
    if t.endswith(("Z", "z")):
        t = t[:-1] + "+00:00"
    try:
        d = datetime.fromisoformat(t)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(value):
    """Parse a YYYY-MM-DD date string; returns a date or None."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool))


def body_json(request):
    """Return the request JSON body as a dict; {} when absent; error when malformed/not an object."""
    raw = request.get_data(cache=True)
    if raw is None or raw.strip() == b"":
        return {}
    try:
        data = request.get_json(force=False, silent=False)
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "Request body is not valid JSON")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def require_field(data, name):
    if name not in data or data[name] is None:
        raise_err(ERR_INVALID_REQUEST, f"Missing required field: {name}")
    return data[name]


def req_string(data, name):
    v = require_field(data, name)
    if not isinstance(v, str):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be a string")
    return v


def req_nonempty_string(data, name):
    v = req_string(data, name)
    if v.strip() == "":
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be a non-empty string")
    return v


def req_int(data, name, min_v=None, max_v=None):
    v = require_field(data, name)
    check_int(v, name, min_v, max_v)
    return v


def check_int(v, name, min_v=None, max_v=None):
    if not is_int(v):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be an integer")
    if min_v is not None and v < min_v:
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be >= {min_v}")
    if max_v is not None and v > max_v:
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be <= {max_v}")


def opt_int(data, name, min_v=None, max_v=None):
    if name not in data or data[name] is None:
        return None
    v = data[name]
    check_int(v, name, min_v, max_v)
    return v


def req_dt(data, name):
    v = require_field(data, name)
    d = parse_dt(v)
    if d is None:
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be an ISO 8601 datetime")
    return d


def opt_dt(data, name):
    if name not in data or data[name] is None:
        return None
    d = parse_dt(data[name])
    if d is None:
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be an ISO 8601 datetime")
    return d


def req_enum(data, name, allowed):
    v = require_field(data, name)
    if not isinstance(v, str) or v not in allowed:
        raise_err(ERR_INVALID_ENUM_VALUE, f"Field {name} must be one of {sorted(allowed)}")
    return v
