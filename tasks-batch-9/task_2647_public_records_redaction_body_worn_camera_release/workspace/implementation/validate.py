"""Schema validation helpers (ladder step 3: ERR_VALIDATION, HTTP 400)."""
from flask import request as flask_request

from db import parse_dt
from errors import fail
from response import (
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_DEFAULT_OFFSET,
    PAGINATION_MAX_LIMIT,
    PAGINATION_MIN_LIMIT,
)

_MISSING = object()


def body():
    """Parse the JSON body.  An absent body is an empty object."""
    raw = flask_request.get_data() or b""
    if not raw.strip():
        return {}
    parsed = flask_request.get_json(silent=True)
    if parsed is None or not isinstance(parsed, dict):
        fail("ERR_VALIDATION", "request body must be a JSON object")
    return parsed


def _present(data, field):
    value = data.get(field, _MISSING)
    if value is _MISSING or value is None:
        return None
    return value


def req_str(data, field):
    value = _present(data, field)
    if value is None:
        fail("ERR_VALIDATION", "%s is required" % field)
    if not isinstance(value, str):
        fail("ERR_VALIDATION", "%s must be a string" % field)
    return value


def opt_str(data, field, default=None):
    value = _present(data, field)
    if value is None:
        return default
    if not isinstance(value, str):
        fail("ERR_VALIDATION", "%s must be a string" % field)
    return value


def req_enum(data, field, allowed):
    value = req_str(data, field)
    if value not in allowed:
        fail("ERR_VALIDATION", "%s must be one of %s" % (field, ", ".join(allowed)))
    return value


def opt_enum(data, field, allowed, default=None):
    value = _present(data, field)
    if value is None:
        return default
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_VALIDATION", "%s must be one of %s" % (field, ", ".join(allowed)))
    return value


def _as_int(field, value, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_VALIDATION", "%s must be an integer" % field)
    if minimum is not None and value < minimum:
        fail("ERR_VALIDATION", "%s must be >= %s" % (field, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_VALIDATION", "%s must be <= %s" % (field, maximum))
    return value


def req_int(data, field, minimum=None, maximum=None):
    value = _present(data, field)
    if value is None:
        fail("ERR_VALIDATION", "%s is required" % field)
    return _as_int(field, value, minimum, maximum)


def opt_int(data, field, default=None, minimum=None, maximum=None):
    value = _present(data, field)
    if value is None:
        return default
    return _as_int(field, value, minimum, maximum)


def req_bool(data, field):
    value = _present(data, field)
    if value is None:
        fail("ERR_VALIDATION", "%s is required" % field)
    if not isinstance(value, bool):
        fail("ERR_VALIDATION", "%s must be a boolean" % field)
    return value


def opt_bool(data, field, default=False):
    value = _present(data, field)
    if value is None:
        return default
    if not isinstance(value, bool):
        fail("ERR_VALIDATION", "%s must be a boolean" % field)
    return value


def req_dt(data, field):
    value = req_str(data, field)
    parsed = parse_dt(value)
    if parsed is None:
        fail("ERR_VALIDATION", "%s must be an ISO-8601 instant" % field)
    return parsed


def opt_dt(data, field, default=None):
    value = _present(data, field)
    if value is None:
        return default
    if not isinstance(value, str):
        fail("ERR_VALIDATION", "%s must be an ISO-8601 instant" % field)
    parsed = parse_dt(value)
    if parsed is None:
        fail("ERR_VALIDATION", "%s must be an ISO-8601 instant" % field)
    return parsed


def req_str_list(data, field):
    value = _present(data, field)
    if value is None:
        fail("ERR_VALIDATION", "%s is required" % field)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        fail("ERR_VALIDATION", "%s must be an array of strings" % field)
    return list(value)


def opt_str_list(data, field, default=None):
    value = _present(data, field)
    if value is None:
        return [] if default is None else list(default)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        fail("ERR_VALIDATION", "%s must be an array of strings" % field)
    return list(value)


# -- query string ---------------------------------------------------------

def query_int(field, default, minimum=None, maximum=None):
    raw = flask_request.args.get(field)
    if raw is None or raw == "":
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        fail("ERR_VALIDATION", "%s must be an integer" % field)
    if minimum is not None and value < minimum:
        fail("ERR_VALIDATION", "%s must be >= %s" % (field, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_VALIDATION", "%s must be <= %s" % (field, maximum))
    return value


def pagination():
    limit = query_int("limit", PAGINATION_DEFAULT_LIMIT,
                      PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT)
    offset = query_int("offset", PAGINATION_DEFAULT_OFFSET, 0, None)
    return limit, offset


def query_enum(field, allowed):
    raw = flask_request.args.get(field)
    if raw is None or raw == "":
        return None
    if raw not in allowed:
        fail("ERR_VALIDATION", "%s must be one of %s" % (field, ", ".join(allowed)))
    return raw


def query_str(field):
    raw = flask_request.args.get(field)
    if raw is None or raw == "":
        return None
    return raw
