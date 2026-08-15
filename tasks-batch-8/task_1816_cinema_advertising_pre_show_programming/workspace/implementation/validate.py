"""Request-shape validation helpers (priority 4) and pagination parsing."""
import re
from datetime import datetime, timezone

from flask import request

from errors import bad_request

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_INT_RE = re.compile(r"^-?\d+$")


def get_body():
    data = request.get_json(force=True, silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise bad_request("request body must be a JSON object")
    return data


def _missing(name):
    raise bad_request(f"missing required field: {name}")


def _bad(name, why):
    raise bad_request(f"invalid field {name}: {why}")


def req_str(body, name):
    if name not in body:
        _missing(name)
    v = body[name]
    if not isinstance(v, str):
        _bad(name, "must be a string")
    return v


def opt_str(body, name):
    if name not in body:
        return None
    v = body[name]
    if not isinstance(v, str):
        _bad(name, "must be a string")
    return v


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_int(body, name, minimum=None):
    if name not in body:
        _missing(name)
    v = body[name]
    if not _is_int(v):
        _bad(name, "must be an integer")
    if minimum is not None and v < minimum:
        _bad(name, f"must be >= {minimum}")
    return v


def opt_int(body, name, minimum=None):
    if name not in body:
        return None
    v = body[name]
    if not _is_int(v):
        _bad(name, "must be an integer")
    if minimum is not None and v < minimum:
        _bad(name, f"must be >= {minimum}")
    return v


def req_enum(body, name, allowed):
    if name not in body:
        _missing(name)
    v = body[name]
    if not isinstance(v, str) or v not in allowed:
        _bad(name, f"must be one of {sorted(allowed)}")
    return v


def opt_enum(body, name, allowed, default=None):
    if name not in body:
        return default
    v = body[name]
    if not isinstance(v, str) or v not in allowed:
        _bad(name, f"must be one of {sorted(allowed)}")
    return v


def parse_date_value(name, v):
    if not isinstance(v, str) or not _DATE_RE.match(v):
        _bad(name, "must be an ISO date YYYY-MM-DD")
    try:
        return datetime.strptime(v, "%Y-%m-%d").date()
    except ValueError:
        _bad(name, "must be a valid ISO date YYYY-MM-DD")


def req_date(body, name):
    if name not in body:
        _missing(name)
    parse_date_value(name, body[name])
    return body[name]


def opt_date(body, name):
    if name not in body:
        return None
    parse_date_value(name, body[name])
    return body[name]


def parse_datetime_value(name, v):
    """Parse an ISO 8601 datetime with explicit timezone; return aware UTC dt."""
    if not isinstance(v, str):
        _bad(name, "must be an ISO 8601 datetime string")
    s = v.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        _bad(name, "must be an ISO 8601 datetime")
    if dt.tzinfo is None:
        _bad(name, "must include a timezone (Z or offset)")
    return dt.astimezone(timezone.utc)


def render_datetime(dt):
    """Render an aware UTC datetime as ISO 8601 with Z; millisecond precision
    only when sub-second information is present."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def req_datetime(body, name):
    if name not in body:
        _missing(name)
    parse_datetime_value(name, body[name])
    return body[name]


def pagination():
    """PRD 2.3: limit default 10, min 1, max 100; offset default 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        if not _INT_RE.match(raw_limit):
            raise bad_request("limit must be an integer")
        limit = int(raw_limit)
    if raw_offset is None:
        offset = 0
    else:
        if not _INT_RE.match(raw_offset):
            raise bad_request("offset must be an integer")
        offset = int(raw_offset)
    if limit < 1 or limit > 100:
        raise bad_request("limit must be between 1 and 100")
    if offset < 0:
        raise bad_request("offset must be >= 0")
    return limit, offset
