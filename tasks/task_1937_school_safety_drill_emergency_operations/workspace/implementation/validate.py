"""Request-body shape validation helpers (priority 4: ERR_VALIDATION)."""
import re
from datetime import date, datetime

from errors import raise_error, ERR_VALIDATION

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def get_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise_error(ERR_VALIDATION, "request body must be a JSON object")
    return body


def reject_unknown(body, allowed):
    extra = [k for k in body.keys() if k not in allowed]
    if extra:
        raise_error(ERR_VALIDATION, f"unknown field(s): {', '.join(sorted(extra))}")


def req_str(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v.strip() == "":
        raise_error(ERR_VALIDATION, f"missing or invalid field: {field}")
    return v


def opt_str(body, field, default=None):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, str):
        raise_error(ERR_VALIDATION, f"invalid field type: {field}")
    return v


def req_int(body, field, minimum=None):
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        raise_error(ERR_VALIDATION, f"missing or invalid integer field: {field}")
    if minimum is not None and v < minimum:
        raise_error(ERR_VALIDATION, f"field {field} must be >= {minimum}")
    return v


def opt_int(body, field, default=None, minimum=None):
    if field not in body or body.get(field) is None:
        return default
    return req_int(body, field, minimum=minimum)


def req_bool(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, bool):
        raise_error(ERR_VALIDATION, f"missing or invalid boolean field: {field}")
    return v


def opt_bool(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_bool(body, field)


def req_enum(body, field, allowed):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v not in allowed:
        raise_error(ERR_VALIDATION, f"missing or invalid enum field: {field}")
    return v


def opt_enum(body, field, allowed, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_enum(body, field, allowed)


def _valid_date(v):
    try:
        date.fromisoformat(v)
        return True
    except (ValueError, TypeError):
        return False


def req_date(body, field):
    v = req_str(body, field)
    if not _valid_date(v):
        raise_error(ERR_VALIDATION, f"invalid ISO date: {field}")
    return v


def opt_date(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_date(body, field)


def req_datetime(body, field):
    v = req_str(body, field)
    s = v.strip()
    try:
        if s.endswith("Z"):
            datetime.fromisoformat(s[:-1] + "+00:00")
        else:
            datetime.fromisoformat(s)
    except (ValueError, TypeError):
        raise_error(ERR_VALIDATION, f"invalid ISO datetime: {field}")
    return v


def req_time(body, field):
    v = req_str(body, field)
    if not _TIME_RE.match(v.strip()):
        raise_error(ERR_VALIDATION, f"invalid HH:MM time: {field}")
    return v.strip()


def req_str_list(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        raise_error(ERR_VALIDATION, f"missing or invalid array field: {field}")
    return v
