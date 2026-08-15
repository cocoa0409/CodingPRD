"""Request body shape validation (priority 3): types, enums, formats, ranges."""
from flask import request

import db
from errors import ApiError


def _is_string(v):
    return isinstance(v, str)


def _is_integer(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_number(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and v == v and v not in (float("inf"), float("-inf")))


def _is_boolean(v):
    return isinstance(v, bool)


def _check(kind, value, opts):
    if kind == "string":
        return _is_string(value)
    if kind == "integer":
        return _is_integer(value)
    if kind == "number":
        return _is_number(value)
    if kind == "boolean":
        return _is_boolean(value)
    if kind == "enum":
        return _is_string(value) and value in opts.get("values", ())
    if kind == "date":
        return db.is_valid_date_string(value)
    if kind == "datetime":
        return db.is_valid_datetime_string(value)
    return False


def validate_body(schema, allow_none_body=True):
    """Validate the JSON request body against schema.

    Schema: field -> (kind, required, opts?) where kind is one of
    string/integer/number/boolean/enum/date/datetime and opts may carry
    values (enum), min / min_exclusive (integer/number), default.
    Returns a dict with every schema key present (absent optional fields
    map to their default or None). Unknown fields are rejected.
    """
    body = request.get_json(silent=True)
    if body is None:
        if not allow_none_body:
            raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
        body = {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    for key in body:
        if key not in schema:
            raise ApiError("ERR_INVALID_REQUEST", 400, "Unknown field: %s" % key)
    out = {}
    for field, spec in schema.items():
        kind, required = spec[0], spec[1]
        opts = spec[2] if len(spec) > 2 else {}
        if field not in body or body[field] is None:
            if required:
                raise ApiError("ERR_INVALID_REQUEST", 400,
                               "Missing required field: %s" % field)
            out[field] = opts.get("default")
            continue
        value = body[field]
        if not _check(kind, value, opts):
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "Invalid value for field: %s" % field)
        if kind in ("integer", "number"):
            if "min" in opts and not value >= opts["min"]:
                raise ApiError("ERR_INVALID_REQUEST", 400,
                               "Field %s must be >= %s" % (field, opts["min"]))
            if "min_exclusive" in opts and not value > opts["min_exclusive"]:
                raise ApiError("ERR_INVALID_REQUEST", 400,
                               "Field %s must be > %s" % (field, opts["min_exclusive"]))
        out[field] = value
    return out
