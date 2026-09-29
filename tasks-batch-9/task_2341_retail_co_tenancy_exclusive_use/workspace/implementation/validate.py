"""Schema validation helpers (validation rung 3 -> ERR_INVALID_REQUEST 400)."""
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError
from util import D, parse_date

MISSING = object()


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    """Parsed JSON object body; absent body is treated as {}."""
    raw = request.get_data()
    if raw is None or len(raw.strip()) == 0:
        return {}
    parsed = request.get_json(silent=True)
    if parsed is None:
        bad("Request body is not valid JSON")
    if not isinstance(parsed, dict):
        bad("Request body must be a JSON object")
    return parsed


def _present(b, key):
    return key in b and b[key] is not None


# ------------------------------------------------------------------ strings

def req_str(b, key):
    if not _present(b, key):
        bad("Field '%s' is required" % key)
    value = b[key]
    if not isinstance(value, str) or value.strip() == "":
        bad("Field '%s' must be a non-empty string" % key)
    return value


def opt_str(b, key, default=None):
    if not _present(b, key):
        return default
    value = b[key]
    if not isinstance(value, str):
        bad("Field '%s' must be a string" % key)
    return value


def opt_id(b, key, default=None):
    """Optional foreign key: string or explicit null."""
    if key not in b or b[key] is None:
        return default
    value = b[key]
    if not isinstance(value, str) or value.strip() == "":
        bad("Field '%s' must be a string id" % key)
    return value


def req_enum(b, key, members):
    value = req_str(b, key)
    if value not in members:
        bad("Field '%s' must be one of %s" % (key, ", ".join(members)))
    return value


def opt_enum(b, key, members, default=None):
    if not _present(b, key):
        return default
    value = b[key]
    if not isinstance(value, str) or value not in members:
        bad("Field '%s' must be one of %s" % (key, ", ".join(members)))
    return value


def req_str_list(b, key, min_len=0):
    if not _present(b, key):
        bad("Field '%s' is required" % key)
    value = b[key]
    if not isinstance(value, list):
        bad("Field '%s' must be an array of strings" % key)
    for item in value:
        if not isinstance(item, str) or item.strip() == "":
            bad("Field '%s' must contain non-empty strings" % key)
    if len(value) < min_len:
        bad("Field '%s' must contain at least %d entry(ies)" % (key, min_len))
    return list(value)


def opt_str_list(b, key, default=None):
    if not _present(b, key):
        return list(default) if default is not None else []
    return req_str_list(b, key)


# ------------------------------------------------------------------ numbers

def _as_int(key, value):
    if isinstance(value, bool):
        bad("Field '%s' must be an integer" % key)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    bad("Field '%s' must be an integer" % key)


def req_int(b, key, minimum=None, maximum=None, exclusive_min=None):
    if not _present(b, key):
        bad("Field '%s' is required" % key)
    value = _as_int(key, b[key])
    _check_int_range(key, value, minimum, maximum, exclusive_min)
    return value


def opt_int(b, key, default=0, minimum=None, maximum=None, exclusive_min=None):
    if not _present(b, key):
        return default
    value = _as_int(key, b[key])
    _check_int_range(key, value, minimum, maximum, exclusive_min)
    return value


def _check_int_range(key, value, minimum, maximum, exclusive_min):
    if minimum is not None and value < minimum:
        bad("Field '%s' must be >= %s" % (key, minimum))
    if exclusive_min is not None and value <= exclusive_min:
        bad("Field '%s' must be > %s" % (key, exclusive_min))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be <= %s" % (key, maximum))


def _as_decimal(key, value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("Field '%s' must be a number" % key)
    try:
        return D(value)
    except (InvalidOperation, ValueError):
        bad("Field '%s' must be a number" % key)


def req_pct(b, key, exclusive_min=None):
    if not _present(b, key):
        bad("Field '%s' is required" % key)
    value = _as_decimal(key, b[key])
    _check_pct(key, value, exclusive_min)
    return value


def opt_pct(b, key, default=None, exclusive_min=None):
    if not _present(b, key):
        return default
    value = _as_decimal(key, b[key])
    _check_pct(key, value, exclusive_min)
    return value


def _check_pct(key, value, exclusive_min):
    if value < 0 or value > 100:
        bad("Field '%s' must be a percentage between 0 and 100" % key)
    if exclusive_min is not None and value <= D(exclusive_min):
        bad("Field '%s' must be > %s" % (key, exclusive_min))


def req_number(b, key, exclusive_min=None, minimum=None):
    if not _present(b, key):
        bad("Field '%s' is required" % key)
    value = _as_decimal(key, b[key])
    if exclusive_min is not None and value <= D(exclusive_min):
        bad("Field '%s' must be > %s" % (key, exclusive_min))
    if minimum is not None and value < D(minimum):
        bad("Field '%s' must be >= %s" % (key, minimum))
    return value


def opt_bool(b, key, default=False):
    if not _present(b, key):
        return default
    value = b[key]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean" % key)
    return value


# -------------------------------------------------------------------- dates

def req_date(b, key):
    value = req_str(b, key)
    parsed = parse_date(value)
    if parsed is None:
        bad("Field '%s' must be an ISO-8601 calendar date (YYYY-MM-DD)" % key)
    return parsed.isoformat()


def opt_date(b, key, default=None):
    if not _present(b, key):
        return default
    return req_date(b, key)


# --------------------------------------------------------------- pagination

def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            bad("Query parameter 'limit' must be an integer")
        if limit < 1 or limit > 100:
            bad("Query parameter 'limit' must be between 1 and 100")
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            bad("Query parameter 'offset' must be an integer")
        if offset < 0:
            bad("Query parameter 'offset' must be >= 0")
    return limit, offset


def filter_value(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value
