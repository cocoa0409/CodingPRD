"""Request body shape validation (PRD 2.8 step 8 -> ERR_INVALID_REQUEST)."""
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError
from store import parse_dt

MISSING = object()


def bad(field=None):
    if field:
        raise ApiError("ERR_INVALID_REQUEST", "Invalid or missing field: %s" % field)
    raise ApiError("ERR_INVALID_REQUEST")


def body():
    """The JSON request body as a dict.  A body-less request yields {}."""
    if not request.data:
        return {}
    try:
        parsed = request.get_json(force=True, silent=True)
    except Exception:  # pragma: no cover - defensive
        parsed = None
    if parsed is None:
        raw = request.data.decode("utf-8", "ignore").strip()
        if raw == "":
            return {}
        bad("body")
    if not isinstance(parsed, dict):
        bad("body")
    return parsed


def present(data, key):
    return key in data and data[key] is not None


def req_str(data, key, min_len=1, max_len=None, pattern=None):
    if not present(data, key):
        bad(key)
    return _check_str(data[key], key, min_len, max_len, pattern)


def opt_str(data, key, min_len=1, max_len=None, pattern=None, default=None):
    if not present(data, key):
        return default
    return _check_str(data[key], key, min_len, max_len, pattern)


def _check_str(value, key, min_len, max_len, pattern):
    if not isinstance(value, str):
        bad(key)
    if min_len is not None and len(value) < min_len:
        bad(key)
    if max_len is not None and len(value) > max_len:
        bad(key)
    if pattern is not None and not pattern.match(value):
        bad(key)
    return value


def req_int(data, key, minimum=None, maximum=None):
    if not present(data, key):
        bad(key)
    return _check_int(data[key], key, minimum, maximum)


def opt_int(data, key, minimum=None, maximum=None, default=None):
    if not present(data, key):
        return default
    return _check_int(data[key], key, minimum, maximum)


def _check_int(value, key, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        bad(key)
    if minimum is not None and value < minimum:
        bad(key)
    if maximum is not None and value > maximum:
        bad(key)
    return value


def req_bool(data, key):
    if not present(data, key):
        bad(key)
    if not isinstance(data[key], bool):
        bad(key)
    return data[key]


def opt_bool(data, key, default=None):
    if not present(data, key):
        return default
    if not isinstance(data[key], bool):
        bad(key)
    return data[key]


def req_num(data, key, minimum=None, maximum=None):
    if not present(data, key):
        bad(key)
    return _check_num(data[key], key, minimum, maximum)


def opt_num(data, key, minimum=None, maximum=None, default=None):
    if not present(data, key):
        return default
    return _check_num(data[key], key, minimum, maximum)


def _check_num(value, key, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad(key)
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        bad(key)
    if minimum is not None and dec < Decimal(str(minimum)):
        bad(key)
    if maximum is not None and dec > Decimal(str(maximum)):
        bad(key)
    return dec


def req_enum(data, key, values):
    if not present(data, key):
        bad(key)
    value = data[key]
    if not isinstance(value, str) or value not in values:
        bad(key)
    return value


def opt_enum(data, key, values, default=None):
    if not present(data, key):
        return default
    return req_enum(data, key, values)


def req_dt(data, key):
    if not present(data, key):
        bad(key)
    if not isinstance(data[key], str):
        bad(key)
    parsed = parse_dt(data[key])
    if parsed is None:
        bad(key)
    return parsed


def opt_dt(data, key, default=None):
    if not present(data, key):
        return default
    return req_dt(data, key)


def window_dt(data, key, required=True):
    """Window bounds.

    A missing bound or a non-string bound is a body-shape failure (step 8);
    a string that does not parse as an ISO-8601 instant is ERR_WINDOW_INVALID
    (step 9, per the error catalogue).
    """
    if not present(data, key):
        if required:
            bad(key)
        return None
    if not isinstance(data[key], str):
        bad(key)
    parsed = parse_dt(data[key])
    if parsed is None:
        raise ApiError("ERR_WINDOW_INVALID")
    return parsed
