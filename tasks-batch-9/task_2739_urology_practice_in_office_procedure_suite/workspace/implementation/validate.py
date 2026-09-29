"""Request-shape validation — validation ladder priority 6 (PRD section 2.8)."""

from flask import request

import response
from errors import ApiError

_MISSING = object()


def bad(message):
    return ApiError("ERR_INVALID_REQUEST", message)


def get_body():
    """Parse the JSON body. An absent body is treated as an empty object."""
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        raise bad("The request body is not valid JSON.")
    if not isinstance(body, dict):
        raise bad("The request body must be a JSON object.")
    return body


def present(body, key):
    return key in body and body[key] is not None


def _fetch(body, key, required):
    if key not in body or body[key] is None:
        if required:
            raise bad("Field '%s' is required." % key)
        return _MISSING
    return body[key]


def str_field(body, key, required=True, default=None):
    value = _fetch(body, key, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str):
        raise bad("Field '%s' must be a string." % key)
    return value


def enum_field(body, key, members, required=True, default=None):
    value = str_field(body, key, required, _MISSING)
    if value is _MISSING:
        return default
    if value not in members:
        raise bad("Field '%s' must be one of: %s." % (key, ", ".join(members)))
    return value


def int_field(body, key, required=True, default=None, minimum=0):
    value = _fetch(body, key, required)
    if value is _MISSING:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad("Field '%s' must be an integer." % key)
    if value < 0:
        raise bad("Field '%s' must be a non-negative integer." % key)
    if value < minimum:
        raise bad("Field '%s' must be at least %d." % (key, minimum))
    return value


def number_field(body, key, required=True, default=None):
    value = _fetch(body, key, required)
    if value is _MISSING:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad("Field '%s' must be a number." % key)
    if value < 0:
        raise bad("Field '%s' may not be negative." % key)
    return value


def bool_field(body, key, required=True, default=None):
    value = _fetch(body, key, required)
    if value is _MISSING:
        return default
    if not isinstance(value, bool):
        raise bad("Field '%s' must be a boolean." % key)
    return value


def date_field(body, key, required=True, default=None):
    import util
    value = str_field(body, key, required, _MISSING)
    if value is _MISSING:
        return default
    parsed = util.parse_date(value)
    if parsed is None:
        raise bad("Field '%s' must be an ISO 8601 date (YYYY-MM-DD)." % key)
    return parsed


def instant_field(body, key, required=True, default=None):
    import util
    value = str_field(body, key, required, _MISSING)
    if value is _MISSING:
        return default
    parsed = util.parse_instant(value)
    if parsed is None:
        raise bad("Field '%s' must be an ISO 8601 UTC instant." % key)
    return parsed


def enum_array_field(body, key, members, required=False, default=None):
    value = _fetch(body, key, required)
    if value is _MISSING:
        return list(default) if default is not None else []
    if not isinstance(value, list):
        raise bad("Field '%s' must be an array." % key)
    out = []
    for item in value:
        if not isinstance(item, str) or item not in members:
            raise bad("Field '%s' may only contain: %s." % (key, ", ".join(members)))
        out.append(item)
    return out


def reject_computed(body, keys):
    """Server-computed fields are rejected as unrecognised input (PRD section 3.2)."""
    for key in keys:
        if key in body:
            raise bad("Field '%s' is server-computed and may not be supplied." % key)


# ------------------------------------------------------------------ pagination
def _query_int(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    negative = text.startswith("-")
    digits = text[1:] if negative or text.startswith("+") else text
    if not digits.isdigit():
        raise bad("Query parameter '%s' must be an integer." % name)
    value = int(text)
    if minimum is not None and value < minimum:
        raise bad("Query parameter '%s' may not be smaller than %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise bad("Query parameter '%s' may not be larger than %d." % (name, maximum))
    return value


def pagination():
    limit = _query_int(
        "limit",
        response.PAGINATION_DEFAULT_LIMIT,
        response.PAGINATION_MIN_LIMIT,
        response.PAGINATION_MAX_LIMIT,
    )
    offset = _query_int("offset", response.PAGINATION_DEFAULT_OFFSET, 0, None)
    return limit, offset


def query_enum(name, members):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in members:
        raise bad("Query parameter '%s' must be one of: %s." % (name, ", ".join(members)))
    return raw


def query_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def query_bool(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    lowered = raw.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    raise bad("Query parameter '%s' must be a boolean." % name)
