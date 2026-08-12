"""Request-body parsing helpers (validation pipeline step 4: ERR_INVALID_REQUEST,
step 5: ERR_INVALID_DATE_RANGE) and pagination parsing."""

import re
from datetime import date

from flask import request

from errors import err

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def req_present(data, field):
    if field not in data or data[field] is None:
        err("ERR_INVALID_REQUEST", f"Missing required field: {field}")
    return data[field]


def req_string(data, field):
    v = req_present(data, field)
    if not isinstance(v, str) or isinstance(v, bool):
        err("ERR_INVALID_REQUEST", f"Field {field} must be a string")
    return v


def req_int(data, field, min_v=None, max_v=None):
    v = req_present(data, field)
    if not isinstance(v, int) or isinstance(v, bool):
        err("ERR_INVALID_REQUEST", f"Field {field} must be an integer")
    if min_v is not None and v < min_v:
        err("ERR_INVALID_REQUEST", f"Field {field} must be >= {min_v}")
    if max_v is not None and v > max_v:
        err("ERR_INVALID_REQUEST", f"Field {field} must be <= {max_v}")
    return v


def opt_int(data, field, min_v=None, max_v=None):
    if field not in data or data[field] is None:
        return None
    return req_int(data, field, min_v=min_v, max_v=max_v)


def opt_string(data, field):
    if field not in data or data[field] is None:
        return None
    return req_string(data, field)


def req_enum(data, field, choices):
    v = req_string(data, field)
    if v not in choices:
        err("ERR_INVALID_REQUEST",
            f"Field {field} must be one of {sorted(choices)}")
    return v


def parse_iso_date(v):
    if not isinstance(v, str) or not _DATE_RE.match(v):
        return None
    try:
        return date.fromisoformat(v)
    except ValueError:
        return None


def req_date(data, field):
    v = req_present(data, field)
    d = parse_iso_date(v)
    if d is None:
        err("ERR_INVALID_REQUEST",
            f"Field {field} must be an ISO date in YYYY-MM-DD form")
    return v


def opt_date(data, field):
    if field not in data or data[field] is None:
        return None
    return req_date(data, field)


def parse_pagination():
    """limit defaults to 10 (min 1, max 100); offset defaults to 0."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def filter_arg_int(name, min_v=None, max_v=None):
    raw = request.args.get(name)
    if raw is None:
        return None
    try:
        v = int(raw)
    except (TypeError, ValueError):
        err("ERR_INVALID_REQUEST", f"Query parameter {name} must be an integer")
    if min_v is not None and v < min_v:
        err("ERR_INVALID_REQUEST", f"Query parameter {name} must be >= {min_v}")
    if max_v is not None and v > max_v:
        err("ERR_INVALID_REQUEST", f"Query parameter {name} must be <= {max_v}")
    return v


def filter_arg_str(name):
    return request.args.get(name)
