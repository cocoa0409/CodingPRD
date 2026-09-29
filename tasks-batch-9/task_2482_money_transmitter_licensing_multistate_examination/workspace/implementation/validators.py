"""Request-shape validation — ladder step 3, ERR_INVALID_REQUEST (PRD §2.7)."""

from flask import request

from db import parse_iso
from errors import ApiError
from response import LIMIT_DEFAULT, LIMIT_MAX, LIMIT_MIN, OFFSET_DEFAULT, OFFSET_MIN

_MISSING = object()


def bad(detail):
    raise ApiError("ERR_INVALID_REQUEST", "Invalid request: %s" % detail)


def get_body():
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        bad("malformed JSON body")
    if not isinstance(data, dict):
        bad("body must be a JSON object")
    return data


def _present(body, name, required):
    if name not in body or body[name] is None:
        if required:
            bad("%s is required" % name)
        return _MISSING
    return body[name]


def v_str(body, name, required=True, allow_empty=False, default=None):
    value = _present(body, name, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str):
        bad("%s must be a string" % name)
    if not allow_empty and value.strip() == "":
        bad("%s must not be empty" % name)
    return value


def v_int(body, name, required=True, minimum=0, maximum=None, default=None):
    value = _present(body, name, required)
    if value is _MISSING:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        bad("%s must be an integer" % name)
    if minimum is not None and value < minimum:
        bad("%s must be >= %d" % (name, minimum))
    if maximum is not None and value > maximum:
        bad("%s must be <= %d" % (name, maximum))
    return value


def v_bool(body, name, required=False, default=None):
    value = _present(body, name, required)
    if value is _MISSING:
        return default
    if not isinstance(value, bool):
        bad("%s must be a boolean" % name)
    return value


def v_enum(body, name, allowed, required=True, default=None):
    value = _present(body, name, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str) or value not in allowed:
        bad("%s must be one of %s" % (name, ", ".join(sorted(allowed))))
    return value


def v_dt(body, name, required=True, default=None):
    """Returns (raw_string, parsed_datetime)."""
    value = _present(body, name, required)
    if value is _MISSING:
        return (default, None)
    if not isinstance(value, str):
        bad("%s must be an ISO 8601 datetime string" % name)
    parsed = parse_iso(value)
    if parsed is None:
        bad("%s must be a well formed ISO 8601 datetime" % name)
    return (value, parsed)


def v_str_list(body, name, required=True, default=None):
    value = _present(body, name, required)
    if value is _MISSING:
        return default if default is not None else []
    if not isinstance(value, list):
        bad("%s must be an array" % name)
    for item in value:
        if not isinstance(item, str) or item == "":
            bad("%s must be an array of ids" % name)
    return value


def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            bad("limit must be an integer")
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            bad("limit must be between %d and %d" % (LIMIT_MIN, LIMIT_MAX))
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            bad("offset must be an integer")
        if offset < OFFSET_MIN:
            bad("offset must be >= %d" % OFFSET_MIN)
    return limit, offset


def q_enum(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        bad("%s must be one of %s" % (name, ", ".join(sorted(allowed))))
    return value


def q_str(name):
    return request.args.get(name)
