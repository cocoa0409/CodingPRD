"""Request-shape validation (admission ladder position 3) and pagination.

Every failure here raises ERR_INVALID_REQUEST (422).
"""
from flask import request

import clock
from errors import ApiError

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    """Parse the JSON body. A body-less request is treated as an empty object."""
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    parsed = request.get_json(silent=True)
    if parsed is None:
        _bad("Request body is not valid JSON.")
    if not isinstance(parsed, dict):
        _bad("Request body must be a JSON object.")
    return parsed


def _present(data, key):
    return key in data and data[key] is not None


def req_str(data, key, allow_empty=False):
    if not _present(data, key):
        _bad("Missing required field '%s'." % key)
    value = data[key]
    if not isinstance(value, str):
        _bad("Field '%s' must be a string." % key)
    if not allow_empty and not value.strip():
        _bad("Field '%s' must not be blank." % key)
    return value


def opt_str(data, key, default=None):
    if not _present(data, key):
        return default
    return req_str(data, key)


def _int_value(data, key):
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int):
        _bad("Field '%s' must be an integer." % key)
    return value


def req_int(data, key, minimum=None, maximum=None):
    if not _present(data, key):
        _bad("Missing required field '%s'." % key)
    value = _int_value(data, key)
    _range(key, value, minimum, maximum)
    return value


def opt_int(data, key, default=None, minimum=None, maximum=None):
    if not _present(data, key):
        return default
    value = _int_value(data, key)
    _range(key, value, minimum, maximum)
    return value


def _range(key, value, minimum, maximum):
    if minimum is not None and value < minimum:
        _bad("Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and value > maximum:
        _bad("Field '%s' must be <= %s." % (key, maximum))


def _num_value(data, key):
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad("Field '%s' must be a number." % key)
    return value


def req_num(data, key, minimum=None, maximum=None, exclusive_min=None):
    if not _present(data, key):
        _bad("Missing required field '%s'." % key)
    value = _num_value(data, key)
    if exclusive_min is not None and value <= exclusive_min:
        _bad("Field '%s' must be greater than %s." % (key, exclusive_min))
    _range(key, value, minimum, maximum)
    return normalize_number(value)


def opt_num(data, key, default=None, minimum=None, maximum=None, exclusive_min=None):
    if not _present(data, key):
        return default
    return req_num(data, key, minimum=minimum, maximum=maximum, exclusive_min=exclusive_min)


def req_bool(data, key):
    if not _present(data, key):
        _bad("Missing required field '%s'." % key)
    value = data[key]
    if not isinstance(value, bool):
        _bad("Field '%s' must be a boolean." % key)
    return value


def opt_bool(data, key, default=False):
    if not _present(data, key):
        return default
    return req_bool(data, key)


def req_enum(data, key, allowed):
    value = req_str(data, key)
    if value not in allowed:
        _bad("Field '%s' must be one of %s." % (key, ", ".join(allowed)))
    return value


def opt_enum(data, key, allowed, default=None):
    if not _present(data, key):
        return default
    return req_enum(data, key, allowed)


def req_enum_array(data, key, allowed):
    if not _present(data, key):
        _bad("Missing required field '%s'." % key)
    value = data[key]
    if not isinstance(value, list) or len(value) == 0:
        _bad("Field '%s' must be a non-empty array." % key)
    seen = []
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            _bad("Field '%s' must be a subset of %s." % (key, ", ".join(allowed)))
        if item not in seen:
            seen.append(item)
    return seen


def req_datetime(data, key):
    value = req_str(data, key)
    parsed = clock.parse_dt(value)
    if parsed is None:
        _bad("Field '%s' must be an ISO 8601 instant." % key)
    return parsed


def req_date(data, key):
    value = req_str(data, key)
    if not clock.is_date_string(value):
        _bad("Field '%s' must be a YYYY-MM-DD calendar date." % key)
    return value


def normalize_number(value):
    """Footage and weights are carried as plain numbers; whole values stay integral."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


# --------------------------------------------------------------- query args --

def pagination():
    limit = _query_int("limit", PAGINATION_DEFAULT_LIMIT, PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT)
    offset = _query_int("offset", PAGINATION_DEFAULT_OFFSET, 0, None)
    return limit, offset


def _query_int(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        _bad("Query parameter '%s' must be an integer." % name)
    _range(name, value, minimum, maximum)
    return value


def query_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in allowed:
        _bad("Query parameter '%s' must be one of %s." % (name, ", ".join(allowed)))
    return raw


def query_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def query_date(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if not clock.is_date_string(raw):
        _bad("Query parameter '%s' must be a YYYY-MM-DD calendar date." % name)
    return raw


def paginate(rows, limit, offset):
    return rows[offset:offset + limit], len(rows)
