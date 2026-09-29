"""Request-body schema validation helpers (priority 4, PRD 2.11)."""
from flask import request

from errors import invalid
from response import (
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_DEFAULT_OFFSET,
    PAGINATION_MAX_LIMIT,
    PAGINATION_MIN_LIMIT,
)

_MISSING = object()


def get_body():
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        raise invalid("Request body must be a JSON object")
    if not isinstance(body, dict):
        raise invalid("Request body must be a JSON object")
    return body


def present(body, key):
    return key in body and body[key] is not None


def req_field(body, key):
    if not present(body, key):
        raise invalid("%s is required" % key)
    return body[key]


def as_str(value, key, allow_empty=False):
    if not isinstance(value, str):
        raise invalid("%s must be a string" % key)
    if not allow_empty and value.strip() == "":
        raise invalid("%s must be a non-empty string" % key)
    return value


def as_int(value, key, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid("%s must be an integer" % key)
    if minimum is not None and value < minimum:
        raise invalid("%s must be >= %s" % (key, minimum))
    if maximum is not None and value > maximum:
        raise invalid("%s must be <= %s" % (key, maximum))
    return value


def as_number(value, key, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise invalid("%s must be a number" % key)
    value = float(value)
    if minimum is not None and value < minimum:
        raise invalid("%s must be >= %s" % (key, minimum))
    if maximum is not None and value > maximum:
        raise invalid("%s must be <= %s" % (key, maximum))
    return value


def as_bool(value, key):
    if not isinstance(value, bool):
        raise invalid("%s must be a boolean" % key)
    return value


def as_enum(value, key, allowed):
    if not isinstance(value, str) or value not in allowed:
        raise invalid("%s must be one of %s" % (key, ", ".join(allowed)))
    return value


# --- convenience: required / optional readers --------------------------------

def rstr(body, key, allow_empty=False):
    return as_str(req_field(body, key), key, allow_empty)


def rint(body, key, minimum=None, maximum=None):
    return as_int(req_field(body, key), key, minimum, maximum)


def rnum(body, key, minimum=None, maximum=None):
    return as_number(req_field(body, key), key, minimum, maximum)


def rbool(body, key):
    return as_bool(req_field(body, key), key)


def renum(body, key, allowed):
    return as_enum(req_field(body, key), key, allowed)


def ostr(body, key, default=None, allow_empty=True):
    if not present(body, key):
        return default
    return as_str(body[key], key, allow_empty)


def oint(body, key, default=None, minimum=None, maximum=None):
    if not present(body, key):
        return default
    return as_int(body[key], key, minimum, maximum)


def obool(body, key, default=None):
    if not present(body, key):
        return default
    return as_bool(body[key], key)


def oenum(body, key, allowed, default=None):
    if not present(body, key):
        return default
    return as_enum(body[key], key, allowed)


def must_be_null(body, key, reason):
    if key in body and body[key] is not None:
        raise invalid("%s %s" % (key, reason))


# --- query parameters --------------------------------------------------------

def pagination_args():
    """limit defaults to 10 (1..100); offset defaults to 0 (>= 0)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise invalid("limit must be an integer between 1 and 100")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise invalid("limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise invalid("offset must be a non-negative integer")
        if offset < 0:
            raise invalid("offset must be a non-negative integer")
    return limit, offset


def enum_filter(name, allowed):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw not in allowed:
        raise invalid("%s must be one of %s" % (name, ", ".join(allowed)))
    return raw


def str_filter(name):
    return request.args.get(name)


def number_filter(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        raise invalid("%s must be a number" % name)
