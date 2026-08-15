"""Request-body shape validation (validation priority 1.5, ERR_INVALID_REQUEST).

Required fields present, enum members legal, datetimes parseable, time ranges
with end strictly after start — all surface ERR_INVALID_REQUEST (HTTP 400)
before any role/scope/existence/business check.
"""
import re
from datetime import date, datetime, timezone

from flask import request

from errors import err


def body_json():
    """Return the request JSON object; a missing body is treated as {} so that
    required-field checks fire; a non-object body is a shape error."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def _bad(field, why):
    err("ERR_INVALID_REQUEST", "Field '%s' %s" % (field, why))


def req_str(data, field):
    v = data.get(field)
    if not isinstance(v, str):
        _bad(field, "is required and must be a string")
    return v


def opt_str(data, field, default=None):
    v = data.get(field, default)
    if v is not None and not isinstance(v, str):
        _bad(field, "must be a string")
    return v


def req_enum(data, field, allowed):
    v = data.get(field)
    if not isinstance(v, str) or v not in allowed:
        _bad(field, "is required and must be one of %s" % sorted(allowed))
    return v


def opt_enum(data, field, allowed, default=None):
    v = data.get(field, default)
    if v is not None and (not isinstance(v, str) or v not in allowed):
        _bad(field, "must be one of %s" % sorted(allowed))
    return v


def req_int(data, field):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        _bad(field, "is required and must be an integer")
    return v


def opt_bool(data, field, default=False):
    v = data.get(field, default)
    if not isinstance(v, bool):
        _bad(field, "must be a boolean")
    return v


def parse_datetime_value(v, field="value"):
    if not isinstance(v, str):
        _bad(field, "is required and must be an ISO 8601 datetime string")
    s = v.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        _bad(field, "is not a parseable ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_datetime(data, field):
    if field not in data:
        _bad(field, "is required")
    return parse_datetime_value(data.get(field), field)


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def req_date(data, field):
    v = data.get(field)
    if not isinstance(v, str) or not _DATE_RE.match(v):
        _bad(field, "is required and must be an ISO date YYYY-MM-DD")
    try:
        return datetime.strptime(v, "%Y-%m-%d").date()
    except ValueError:
        _bad(field, "is not a valid calendar date")


def req_str_list(data, field, allow_empty=True):
    v = data.get(field)
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        _bad(field, "is required and must be an array of strings")
    if not allow_empty and not v:
        _bad(field, "must name at least one entry")
    return list(v)


def require_end_after_start(start, end, start_field="start", end_field="end"):
    if not end > start:
        err("ERR_INVALID_REQUEST",
            "Field '%s' must be strictly later than '%s'" % (end_field, start_field))
