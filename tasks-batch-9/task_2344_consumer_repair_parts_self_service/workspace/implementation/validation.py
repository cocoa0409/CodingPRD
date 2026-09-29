"""Request-body parsing and the band-2 structural / range / date-range checks."""
from flask import request

from errors import ApiError
from util import parse_ts


class F(object):
    """A declared body field."""

    def __init__(self, name, kind, required=False, enum=None, default=None):
        self.name = name
        self.kind = kind
        self.required = required
        self.enum = enum
        self.default = default


def raw_body():
    if not request.data:
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "Body is not valid JSON.")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Body must be a JSON object.")
    return payload


def _bad(name, why):
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (name, why))


def _coerce(field, value):
    kind = field.kind
    if kind == "string":
        if not isinstance(value, str):
            _bad(field.name, "must be a string")
        return value
    if kind == "enum":
        if not isinstance(value, str):
            _bad(field.name, "must be a string")
        if field.enum is not None and value not in field.enum:
            _bad(field.name, "is not one of %s" % ", ".join(field.enum))
        return value
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            _bad(field.name, "must be an integer")
        return value
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            _bad(field.name, "must be a number")
        return value
    if kind == "bool":
        if not isinstance(value, bool):
            _bad(field.name, "must be a boolean")
        return value
    if kind == "datetime":
        try:
            return parse_ts(value)
        except ValueError:
            _bad(field.name, "must be an ISO 8601 timestamp")
    if kind == "string_list":
        if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
            _bad(field.name, "must be an array of strings")
        return value
    raise AssertionError("unknown kind %s" % kind)


def read_body(fields):
    payload = raw_body()
    known = set(f.name for f in fields)
    for key in payload.keys():
        if key not in known:
            raise ApiError("ERR_INVALID_REQUEST", "Unknown field '%s'." % key)
    out = {}
    for field in fields:
        if field.name not in payload or payload[field.name] is None:
            if field.required:
                _bad(field.name, "is required")
            out[field.name] = field.default
            continue
        out[field.name] = _coerce(field, payload[field.name])
    return out


# --------------------------------------------------------------------------
# band 2 helpers
# --------------------------------------------------------------------------

def check_range(condition, message):
    """Raise ERR_INVALID_RANGE when `condition` is truthy."""
    if condition:
        raise ApiError("ERR_INVALID_RANGE", message)


def int_range(value, name, low=None, high=None):
    if value is None:
        return
    if low is not None and value < low:
        raise ApiError("ERR_INVALID_RANGE", "%s may not be below %s." % (name, low))
    if high is not None and value > high:
        raise ApiError("ERR_INVALID_RANGE", "%s may not exceed %s." % (name, high))


def str_len(value, name, low, high):
    if value is None:
        return
    if len(value) < low or len(value) > high:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "%s must be between %d and %d characters." % (name, low, high),
        )


def check_date_range(condition, message):
    if condition:
        raise ApiError("ERR_INVALID_DATE_RANGE", message)


def query_enum(name, options, default=None):
    value = request.args.get(name)
    if value is None or value == "":
        return default
    if value not in options:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Query parameter '%s' is not one of %s." % (name, ", ".join(options)),
        )
    return value


def query_int(name, required=False):
    value = request.args.get(name)
    if value is None or value == "":
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' is required." % name)
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)


def query_bool(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    lowered = value.lower()
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no"):
        return False
    raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be a boolean." % name)


def query_ts(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    try:
        return parse_ts(value)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be a date." % name)
