"""Request-shape validation (priority 6) and pagination shape (priority 7).
Every failure here is ERR_INVALID_REQUEST / HTTP 400."""
from flask import request

import clock
from errors import ApiError

MISSING = object()


def _bad(msg):
    raise ApiError("ERR_INVALID_REQUEST", msg)


def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        _bad("Request body must be a JSON object.")
    return data


def present(data, name):
    return name in data and data[name] is not None


def str_req(data, name):
    value = data.get(name, MISSING)
    if value is MISSING or value is None or not isinstance(value, str) or value == "":
        _bad("Field '%s' is required and must be a non-empty string." % name)
    return value


def str_opt(data, name, default=None):
    if not present(data, name):
        return default
    value = data[name]
    if not isinstance(value, str):
        _bad("Field '%s' must be a string." % name)
    return value


def int_req(data, name, minimum=None, maximum=None):
    value = data.get(name, MISSING)
    if value is MISSING or value is None or isinstance(value, bool) or not isinstance(value, int):
        _bad("Field '%s' is required and must be an integer." % name)
    _range(name, value, minimum, maximum)
    return value


def int_opt(data, name, default=None, minimum=None, maximum=None):
    if not present(data, name):
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int):
        _bad("Field '%s' must be an integer." % name)
    _range(name, value, minimum, maximum)
    return value


def num_req(data, name, minimum=None, maximum=None):
    value = data.get(name, MISSING)
    if value is MISSING or value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad("Field '%s' is required and must be a number." % name)
    _range(name, value, minimum, maximum)
    return value


def num_opt(data, name, default=None, minimum=None, maximum=None):
    if not present(data, name):
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad("Field '%s' must be a number." % name)
    _range(name, value, minimum, maximum)
    return value


def _range(name, value, minimum, maximum):
    if minimum is not None and value < minimum:
        _bad("Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and value > maximum:
        _bad("Field '%s' must be at most %s." % (name, maximum))


def bool_opt(data, name, default=None):
    if not present(data, name):
        return default
    value = data[name]
    if not isinstance(value, bool):
        _bad("Field '%s' must be a boolean." % name)
    return value


def enum_req(data, name, allowed):
    value = str_req(data, name)
    if value not in allowed:
        _bad("Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def enum_opt(data, name, allowed, default=None):
    if not present(data, name):
        return default
    value = str_opt(data, name)
    if value not in allowed:
        _bad("Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def date_req(data, name):
    value = str_req(data, name)
    parsed = clock.parse_date(value)
    if parsed is None:
        _bad("Field '%s' must be a YYYY-MM-DD date." % name)
    return value


def date_opt(data, name, default=None):
    if not present(data, name):
        return default
    value = str_opt(data, name)
    parsed = clock.parse_date(value)
    if parsed is None:
        _bad("Field '%s' must be a YYYY-MM-DD date." % name)
    return value


def instant_req(data, name):
    value = str_req(data, name)
    if clock.parse_instant(value) is None:
        _bad("Field '%s' must be an ISO 8601 UTC instant." % name)
    return value


def id_opt(data, name):
    """A nullable foreign-key string field."""
    if name not in data or data[name] is None:
        return None
    value = data[name]
    if not isinstance(value, str) or value == "":
        _bad("Field '%s' must be a string identifier." % name)
    return value


def pagination():
    limit = _int_param("limit", 10, 1, 100)
    offset = _int_param("offset", 0, 0, None)
    return limit, offset


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        _bad("Query parameter '%s' must be an integer." % name)
    if str(value) != raw.strip():
        _bad("Query parameter '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        _bad("Query parameter '%s' must be at least %s." % (name, minimum))
    if maximum is not None and value > maximum:
        _bad("Query parameter '%s' must be at most %s." % (name, maximum))
    return value


def filter_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in allowed:
        _bad("Query parameter '%s' must be one of %s." % (name, ", ".join(allowed)))
    return raw


def filter_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def filter_bool(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    low = raw.lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    _bad("Query parameter '%s' must be a boolean." % name)


def filter_date(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if clock.parse_date(raw) is None:
        _bad("Query parameter '%s' must be a YYYY-MM-DD date." % name)
    return raw
