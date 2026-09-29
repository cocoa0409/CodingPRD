"""Request shape validation -- validation rung 4 (ERR_INVALID_REQUEST)."""

from decimal import Decimal, InvalidOperation

from flask import request

import db
from errors import ApiError
from response import (
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_DEFAULT_OFFSET,
    PAGINATION_MAX_LIMIT,
    PAGINATION_MIN_LIMIT,
)

_MISSING = object()


def invalid(message):
    return ApiError("ERR_INVALID_REQUEST", message)


def body_object(required=True):
    data = request.get_json(silent=True)
    if data is None:
        if required:
            raise invalid("A JSON object body is required.")
        return {}
    if not isinstance(data, dict):
        raise invalid("The request body must be a JSON object.")
    return data


def _present(body, key):
    return key in body and body[key] is not None


def req_str(body, key, min_len=1, max_len=None, pattern=None):
    if not _present(body, key):
        raise invalid("%s is required." % key)
    value = body[key]
    if not isinstance(value, str):
        raise invalid("%s must be a string." % key)
    return _check_str(key, value, min_len, max_len, pattern)


def opt_str(body, key, min_len=1, max_len=None, pattern=None, default=None):
    if not _present(body, key):
        return default
    value = body[key]
    if not isinstance(value, str):
        raise invalid("%s must be a string." % key)
    return _check_str(key, value, min_len, max_len, pattern)


def _check_str(key, value, min_len, max_len, pattern):
    trimmed = value.strip()
    if min_len is not None and len(trimmed) < min_len:
        raise invalid("%s must be at least %d characters." % (key, min_len))
    if max_len is not None and len(trimmed) > max_len:
        raise invalid("%s must be at most %d characters." % (key, max_len))
    if pattern is not None and not pattern.match(trimmed):
        raise invalid("%s does not match the required format." % key)
    return trimmed


def raw_str(body, key):
    """A nullable free-text field: null/absent -> None, otherwise the raw string."""
    if not _present(body, key):
        return None
    value = body[key]
    if not isinstance(value, str):
        raise invalid("%s must be a string." % key)
    return value


def req_enum(body, key, choices):
    if not _present(body, key):
        raise invalid("%s is required." % key)
    value = body[key]
    if not isinstance(value, str) or value not in choices:
        raise invalid("%s must be one of %s." % (key, ", ".join(sorted(choices))))
    return value


def opt_enum(body, key, choices, default=None):
    if not _present(body, key):
        return default
    value = body[key]
    if not isinstance(value, str) or value not in choices:
        raise invalid("%s must be one of %s." % (key, ", ".join(sorted(choices))))
    return value


def _as_int(key, value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid("%s must be an integer." % key)
    if minimum is not None and value < minimum:
        raise invalid("%s must be at least %d." % (key, minimum))
    if maximum is not None and value > maximum:
        raise invalid("%s must be at most %d." % (key, maximum))
    return value


def req_int(body, key, minimum=None, maximum=None):
    if not _present(body, key):
        raise invalid("%s is required." % key)
    return _as_int(key, body[key], minimum, maximum)


def opt_int(body, key, minimum=None, maximum=None, default=None):
    if not _present(body, key):
        return default
    return _as_int(key, body[key], minimum, maximum)


def _as_decimal(key, value, minimum, maximum, places):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise invalid("%s must be a number." % key)
    try:
        dec = Decimal(str(value))
    except InvalidOperation:
        raise invalid("%s must be a number." % key)
    if places is not None and -dec.as_tuple().exponent > places:
        raise invalid("%s may carry at most %d decimal places." % (key, places))
    if minimum is not None and dec < Decimal(str(minimum)):
        raise invalid("%s must be at least %s." % (key, minimum))
    if maximum is not None and dec > Decimal(str(maximum)):
        raise invalid("%s must be at most %s." % (key, maximum))
    return float(dec)


def req_decimal(body, key, minimum=None, maximum=None, places=None):
    if not _present(body, key):
        raise invalid("%s is required." % key)
    return _as_decimal(key, body[key], minimum, maximum, places)


def opt_decimal(body, key, minimum=None, maximum=None, places=None, default=None):
    if not _present(body, key):
        return default
    return _as_decimal(key, body[key], minimum, maximum, places)


def req_bool(body, key):
    if not _present(body, key):
        raise invalid("%s is required." % key)
    value = body[key]
    if not isinstance(value, bool):
        raise invalid("%s must be a boolean." % key)
    return value


def opt_bool(body, key, default=None):
    if not _present(body, key):
        return default
    value = body[key]
    if not isinstance(value, bool):
        raise invalid("%s must be a boolean." % key)
    return value


def req_ts(body, key):
    if not _present(body, key):
        raise invalid("%s is required." % key)
    parsed = db.parse_ts(body[key])
    if parsed is None:
        raise invalid("%s must be an ISO 8601 timestamp." % key)
    return parsed


def opt_ts(body, key, default=None):
    if not _present(body, key):
        return default
    parsed = db.parse_ts(body[key])
    if parsed is None:
        raise invalid("%s must be an ISO 8601 timestamp." % key)
    return parsed


def req_id(body, key):
    if not _present(body, key):
        raise invalid("%s is required." % key)
    value = body[key]
    if not isinstance(value, str) or not value.strip():
        raise invalid("%s must be a non-empty string." % key)
    return value.strip()


def opt_id(body, key, default=None):
    if not _present(body, key):
        return default
    value = body[key]
    if not isinstance(value, str) or not value.strip():
        raise invalid("%s must be a non-empty string." % key)
    return value.strip()


def req_array(body, key, min_len=None, max_len=None):
    if not _present(body, key):
        raise invalid("%s is required." % key)
    value = body[key]
    if not isinstance(value, list):
        raise invalid("%s must be an array." % key)
    if min_len is not None and len(value) < min_len:
        raise invalid("%s must hold at least %d element(s)." % (key, min_len))
    if max_len is not None and len(value) > max_len:
        raise invalid("%s must hold at most %d element(s)." % (key, max_len))
    return value


def opt_array(body, key, min_len=None, max_len=None, default=None):
    if not _present(body, key):
        return [] if default is None else default
    value = body[key]
    if not isinstance(value, list):
        raise invalid("%s must be an array." % key)
    if min_len is not None and len(value) < min_len:
        raise invalid("%s must hold at least %d element(s)." % (key, min_len))
    if max_len is not None and len(value) > max_len:
        raise invalid("%s must hold at most %d element(s)." % (key, max_len))
    return value


def sub_object(value, key):
    if not isinstance(value, dict):
        raise invalid("%s must be a JSON object." % key)
    return value


# --------------------------------------------------------------------------
# Query string
# --------------------------------------------------------------------------

def query_pagination():
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        limit = _query_int("limit", raw_limit, PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT)
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        offset = _query_int("offset", raw_offset, 0, None)
    return limit, offset


def _query_int(name, raw, minimum, maximum):
    text = raw.strip()
    if not text:
        raise invalid("%s must be an integer." % name)
    try:
        value = int(text, 10)
    except ValueError:
        raise invalid("%s must be an integer." % name)
    if minimum is not None and value < minimum:
        raise invalid("%s must be at least %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise invalid("%s must be at most %d." % (name, maximum))
    return value


def query_enum(name, choices, default=None):
    raw = request.args.get(name)
    if raw is None:
        return default
    if raw not in choices:
        raise invalid("%s must be one of %s." % (name, ", ".join(sorted(choices))))
    return raw


def query_str(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    return raw
