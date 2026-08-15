"""Request-shape validation helpers (priority 2: ERR_VALIDATION)."""

from datetime import date

from flask import request

from errors import ApiError, ERR_VALIDATION
import clock


def _fail(msg):
    raise ApiError(ERR_VALIDATION, 400, msg)


def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        _fail("Request body must be a JSON object")
    return data


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _check_field(data, name, kind, required, enum=None):
    if name not in data or data[name] is None:
        if required:
            _fail("Missing required field: %s" % name)
        return None
    v = data[name]
    if kind == "str":
        if not isinstance(v, str):
            _fail("Field %s must be a string" % name)
    elif kind == "int":
        if not _is_int(v):
            _fail("Field %s must be an integer" % name)
    elif kind == "pint":
        if not _is_int(v) or v <= 0:
            _fail("Field %s must be a positive integer" % name)
    elif kind == "nnint":
        if not _is_int(v) or v < 0:
            _fail("Field %s must be a non-negative integer" % name)
    elif kind == "bool":
        if not isinstance(v, bool):
            _fail("Field %s must be a boolean" % name)
    elif kind == "number":
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            _fail("Field %s must be a number" % name)
    elif kind == "date":
        if not isinstance(v, str):
            _fail("Field %s must be an ISO date string" % name)
        try:
            date.fromisoformat(v)
        except ValueError:
            _fail("Field %s must be a valid ISO date (YYYY-MM-DD)" % name)
    elif kind == "datetime":
        if not isinstance(v, str):
            _fail("Field %s must be an ISO 8601 datetime string" % name)
        try:
            clock.parse_dt(v)
        except (ValueError, TypeError):
            _fail("Field %s must be a valid ISO 8601 datetime" % name)
    if enum is not None and v not in enum:
        _fail("Field %s must be one of %s" % (name, sorted(enum)))
    return v


def validate(data, spec):
    """spec: list of (name, kind, required) or (name, kind, required, enum).
    Returns dict of validated values (only keys present in data)."""
    out = {}
    for entry in spec:
        name, kind, required = entry[0], entry[1], entry[2]
        enum = entry[3] if len(entry) > 3 else None
        v = _check_field(data, name, kind, required, enum)
        if v is not None or name in data:
            out[name] = v
    return out


def parse_pagination():
    """limit: default 10, range 1..100; offset: default 0, >= 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            _fail("limit must be an integer")
        if isinstance(limit, bool) or limit < 1 or limit > 100:
            _fail("limit must be within 1..100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            _fail("offset must be an integer")
        if offset < 0:
            _fail("offset must be >= 0")
    return limit, offset
