"""Request-body shape validation (ladder rung 15, ERR_INVALID_REQUEST)."""
from flask import request

from errors import ApiError
from store import parse_date, parse_iso

MISSING = object()


def bad(message):
    return ApiError("ERR_INVALID_REQUEST", message)


def get_body(allow_empty=True):
    if not request.data:
        if allow_empty:
            return {}
        raise bad("A JSON request body is required.")
    body = request.get_json(silent=True)
    if body is None:
        raise bad("The request body is not valid JSON.")
    if not isinstance(body, dict):
        raise bad("The request body must be a JSON object.")
    return body


def _fetch(body, key, required):
    if key not in body or body.get(key) is None:
        if required:
            raise bad("Field '%s' is required." % key)
        return MISSING
    return body[key]


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def v_str(body, key, required=True, allow_blank=False):
    value = _fetch(body, key, required)
    if value is MISSING:
        return None
    if not isinstance(value, str):
        raise bad("Field '%s' must be a string." % key)
    if not allow_blank and value.strip() == "":
        raise bad("Field '%s' may not be blank." % key)
    return value


def v_enum(body, key, choices, required=True):
    value = v_str(body, key, required)
    if value is None:
        return None
    if value not in choices:
        raise bad("Field '%s' must be one of %s." % (key, ", ".join(choices)))
    return value


def v_num(body, key, required=True, minimum=None, maximum=None,
          exclusive_min=False, exclusive_max=False):
    value = _fetch(body, key, required)
    if value is MISSING:
        return None
    if not is_number(value):
        raise bad("Field '%s' must be a number." % key)
    if minimum is not None:
        if exclusive_min and not value > minimum:
            raise bad("Field '%s' must be greater than %s." % (key, minimum))
        if not exclusive_min and value < minimum:
            raise bad("Field '%s' may not be smaller than %s." % (key, minimum))
    if maximum is not None:
        if exclusive_max and not value < maximum:
            raise bad("Field '%s' must be smaller than %s." % (key, maximum))
        if not exclusive_max and value > maximum:
            raise bad("Field '%s' may not be larger than %s." % (key, maximum))
    return value


def v_int(body, key, required=True, minimum=None, maximum=None):
    value = _fetch(body, key, required)
    if value is MISSING:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, float) and float(value).is_integer():
            value = int(value)
        else:
            raise bad("Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        raise bad("Field '%s' may not be smaller than %d." % (key, minimum))
    if maximum is not None and value > maximum:
        raise bad("Field '%s' may not be larger than %d." % (key, maximum))
    return value


def v_bool(body, key, required=True, default=None):
    value = _fetch(body, key, required)
    if value is MISSING:
        return default
    if not isinstance(value, bool):
        raise bad("Field '%s' must be a boolean." % key)
    return value


def v_enum_array(body, key, choices=None, required=True, default=None):
    value = _fetch(body, key, required)
    if value is MISSING:
        return default
    if not isinstance(value, list):
        raise bad("Field '%s' must be an array." % key)
    if len(value) == 0:
        raise bad("Field '%s' may not be empty." % key)
    seen = set()
    for item in value:
        if not isinstance(item, str):
            raise bad("Field '%s' must contain strings." % key)
        if choices is not None and item not in choices:
            raise bad("Field '%s' contains an undeclared value '%s'."
                      % (key, item))
        if item in seen:
            raise bad("Field '%s' must contain distinct members." % key)
        seen.add(item)
    return list(value)


def v_optional_enum_array(body, key, choices=None, default=None):
    """Array that may be supplied as an empty list."""
    if key not in body or body.get(key) is None:
        return default
    value = body[key]
    if not isinstance(value, list):
        raise bad("Field '%s' must be an array." % key)
    seen = set()
    for item in value:
        if not isinstance(item, str):
            raise bad("Field '%s' must contain strings." % key)
        if choices is not None and item not in choices:
            raise bad("Field '%s' contains an undeclared value '%s'."
                      % (key, item))
        if item in seen:
            raise bad("Field '%s' must contain distinct members." % key)
        seen.add(item)
    return list(value)


def v_date(body, key, required=True):
    value = v_str(body, key, required)
    if value is None:
        return None
    parsed = parse_date(value)
    if parsed is None:
        raise bad("Field '%s' must be a YYYY-MM-DD date." % key)
    return parsed


def v_datetime(body, key, required=True):
    value = v_str(body, key, required)
    if value is None:
        return None
    parsed = parse_iso(value)
    if parsed is None:
        raise bad("Field '%s' must be an ISO 8601 timestamp." % key)
    return parsed
