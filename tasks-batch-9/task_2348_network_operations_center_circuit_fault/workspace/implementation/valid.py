"""Request-shape validation helpers (band 6: ERR_INVALID_REQUEST)."""

from decimal import Decimal, InvalidOperation

from flask import request

from errors import fail
from timeutil import parse

MISSING = object()

PAGINATION_LIMIT_DEFAULT = 10
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
PAGINATION_OFFSET_DEFAULT = 0
PAGINATION_OFFSET_MIN = 0


def body():
    """The JSON request body as a dict; an absent body reads as {}."""
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    data = request.get_json(silent=True, force=True)
    if data is None or not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def _present(b, key):
    return key in b and b[key] is not None


def req_string(b, key, allow_empty=False):
    if not _present(b, key):
        fail("ERR_INVALID_REQUEST", "%s is required." % key)
    value = b[key]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "%s must be a string." % key)
    if not allow_empty and value.strip() == "":
        fail("ERR_INVALID_REQUEST", "%s must not be empty." % key)
    return value


def opt_string(b, key, default=None, allow_empty=True):
    if not _present(b, key):
        return default
    value = b[key]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "%s must be a string." % key)
    if not allow_empty and value.strip() == "":
        fail("ERR_INVALID_REQUEST", "%s must not be empty." % key)
    return value


def req_enum(b, key, allowed):
    value = req_string(b, key)
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s." % (key, ", ".join(allowed)))
    return value


def opt_enum(b, key, allowed, default=None):
    if not _present(b, key):
        return default
    value = b[key]
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s." % (key, ", ".join(allowed)))
    return value


def _as_int(key, value, minimum=None, maximum=None):
    if isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "%s must be an integer." % key)
    if isinstance(value, int):
        number = value
    elif isinstance(value, float):
        if not float(value).is_integer():
            fail("ERR_INVALID_REQUEST", "%s must be an integer." % key)
        number = int(value)
    else:
        fail("ERR_INVALID_REQUEST", "%s must be an integer." % key)
    if minimum is not None and number < minimum:
        fail("ERR_INVALID_REQUEST", "%s must be >= %s." % (key, minimum))
    if maximum is not None and number > maximum:
        fail("ERR_INVALID_REQUEST", "%s must be <= %s." % (key, maximum))
    return number


def req_int(b, key, minimum=None, maximum=None):
    if not _present(b, key):
        fail("ERR_INVALID_REQUEST", "%s is required." % key)
    return _as_int(key, b[key], minimum, maximum)


def opt_int(b, key, default=None, minimum=None, maximum=None):
    if not _present(b, key):
        return default
    return _as_int(key, b[key], minimum, maximum)


def _as_decimal(key, value, minimum=None, maximum=None, exclusive_min=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", "%s must be a number." % key)
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        fail("ERR_INVALID_REQUEST", "%s must be a number." % key)
    if minimum is not None:
        if exclusive_min and number <= minimum:
            fail("ERR_INVALID_REQUEST", "%s must be greater than %s." % (key, minimum))
        if not exclusive_min and number < minimum:
            fail("ERR_INVALID_REQUEST", "%s must be >= %s." % (key, minimum))
    if maximum is not None and number > maximum:
        fail("ERR_INVALID_REQUEST", "%s must be <= %s." % (key, maximum))
    return number


def req_decimal(b, key, minimum=None, maximum=None, exclusive_min=False):
    if not _present(b, key):
        fail("ERR_INVALID_REQUEST", "%s is required." % key)
    return _as_decimal(key, b[key], minimum, maximum, exclusive_min)


def opt_decimal(b, key, default=None, minimum=None, maximum=None, exclusive_min=False):
    if not _present(b, key):
        return default
    return _as_decimal(key, b[key], minimum, maximum, exclusive_min)


def req_bool(b, key):
    if not _present(b, key):
        fail("ERR_INVALID_REQUEST", "%s is required." % key)
    value = b[key]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "%s must be a boolean." % key)
    return value


def opt_bool(b, key, default=None):
    if not _present(b, key):
        return default
    value = b[key]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "%s must be a boolean." % key)
    return value


def req_ts(b, key):
    if not _present(b, key):
        fail("ERR_INVALID_REQUEST", "%s is required." % key)
    value = parse(b[key])
    if value is None:
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 8601 timestamp." % key)
    return value


def opt_ts(b, key, default=None):
    if not _present(b, key):
        return default
    value = parse(b[key])
    if value is None:
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 8601 timestamp." % key)
    return value


def opt_ref(b, key):
    """A reference id supplied in the body, or None when absent/null."""
    if not _present(b, key):
        return None
    value = b[key]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "%s must be a string." % key)
    return value


# --------------------------------------------------------------------------
# query string
# --------------------------------------------------------------------------


def pagination():
    limit = PAGINATION_LIMIT_DEFAULT
    offset = PAGINATION_OFFSET_DEFAULT
    raw_limit = request.args.get("limit")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < PAGINATION_LIMIT_MIN or limit > PAGINATION_LIMIT_MAX:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    raw_offset = request.args.get("offset")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < PAGINATION_OFFSET_MIN:
            fail("ERR_INVALID_REQUEST", "offset must be >= 0.")
    return limit, offset


def q_enum(name, allowed):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s." % (name, ", ".join(allowed)))
    return value


def q_string(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def q_int(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "%s must be an integer." % name)


def q_ts(name, required=False):
    value = request.args.get(name)
    if value is None or value == "":
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required." % name)
        return None
    parsed = parse(value)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 8601 timestamp." % name)
    return parsed
