"""Payload shape validation (validation band 3 -> ERR_INVALID_REQUEST)."""
from flask import request

import clock
from errors import fail

_MISSING = object()


def body():
    if request.method in ("POST", "PATCH", "PUT"):
        raw = request.get_data(cache=True, as_text=True)
        if raw is None or raw.strip() == "":
            return {}
        try:
            data = request.get_json(force=True, silent=False)
        except Exception:
            fail("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
        if data is None:
            return {}
        if not isinstance(data, dict):
            fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
        return data
    return {}


def present(data, name):
    return name in data and data[name] is not None


def req_str(data, name, allow_empty=True):
    if not present(data, name):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
    value = data[name]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % name)
    if not allow_empty and value.strip() == "":
        fail("ERR_INVALID_REQUEST", "Field '%s' must not be empty." % name)
    return value


def opt_str(data, name, default=None):
    if not present(data, name):
        return default
    value = data[name]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % name)
    return value


def _check_int(name, value):
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % name)
    return value


def req_int(data, name, minimum=None, maximum=None):
    if not present(data, name):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
    value = _check_int(name, data[name])
    _range(name, value, minimum, maximum)
    return value


def opt_int(data, name, default=None, minimum=None, maximum=None):
    if not present(data, name):
        return default
    value = _check_int(name, data[name])
    _range(name, value, minimum, maximum)
    return value


def _check_num(name, value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % name)
    return value


def req_num(data, name, minimum=None, maximum=None):
    if not present(data, name):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
    value = _check_num(name, data[name])
    _range(name, value, minimum, maximum)
    return value


def opt_num(data, name, default=None, minimum=None, maximum=None):
    if not present(data, name):
        return default
    value = _check_num(name, data[name])
    _range(name, value, minimum, maximum)
    return value


def _range(name, value, minimum, maximum):
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be at most %s." % (name, maximum))


def req_bool(data, name):
    if not present(data, name):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
    value = data[name]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % name)
    return value


def opt_bool(data, name, default=None):
    if not present(data, name):
        return default
    value = data[name]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % name)
    return value


def req_enum(data, name, allowed):
    value = req_str(data, name)
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def opt_enum(data, name, allowed, default=None):
    if not present(data, name):
        return default
    value = opt_str(data, name)
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def req_ts(data, name):
    raw = req_str(data, name)
    parsed = clock.parse(raw)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 timestamp." % name)
    return parsed


def opt_ts(data, name, default=None):
    if not present(data, name):
        return default
    raw = data[name]
    if not isinstance(raw, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 timestamp." % name)
    parsed = clock.parse(raw)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 timestamp." % name)
    return parsed


def req_id(data, name):
    if not present(data, name):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
    value = data[name]
    if not isinstance(value, str) or value.strip() == "":
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a non-empty string identifier." % name)
    return value


def opt_id(data, name, default=None):
    if not present(data, name):
        return default
    value = data[name]
    if not isinstance(value, str) or value.strip() == "":
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a non-empty string identifier." % name)
    return value


def opt_id_list(data, name, default=None):
    if not present(data, name):
        return default if default is not None else []
    value = data[name]
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an array." % name)
    for entry in value:
        if not isinstance(entry, str) or entry.strip() == "":
            fail("ERR_INVALID_REQUEST", "Field '%s' must contain string identifiers." % name)
    return value


def query_enum(name, allowed):
    """Query-string filters are matched literally; no existence validation."""
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
    fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be a boolean." % name)


def query_int(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    text = raw.strip()
    digits = text[1:] if text.startswith("-") else text
    if not digits.isdigit():
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)
    return int(text)
