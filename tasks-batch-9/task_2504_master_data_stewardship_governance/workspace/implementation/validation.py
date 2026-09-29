"""Request body / query-string schema validation (priority 4) and pagination."""

import json

from flask import request

from errors import invalid
from util import dec, parse_iso

_MISSING = object()


def body():
    raw = request.get_data(as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        payload = json.loads(raw)
    except Exception:
        invalid("Request body is not valid JSON.")
    if not isinstance(payload, dict):
        invalid("Request body must be a JSON object.")
    return payload


def _present(data, key):
    return key in data and data[key] is not None


# --------------------------------------------------------------------------
# strings
# --------------------------------------------------------------------------

def req_str(data, key, min_len=1, max_len=None):
    if not _present(data, key):
        invalid("Field '%s' is required." % key)
    return opt_str(data, key, min_len, max_len)


def opt_str(data, key, min_len=1, max_len=None, default=None):
    if not _present(data, key):
        return default
    value = data[key]
    if not isinstance(value, str):
        invalid("Field '%s' must be a string." % key)
    if min_len is not None and len(value) < min_len:
        invalid("Field '%s' must be at least %d characters." % (key, min_len))
    if max_len is not None and len(value) > max_len:
        invalid("Field '%s' must be at most %d characters." % (key, max_len))
    return value


# --------------------------------------------------------------------------
# enums
# --------------------------------------------------------------------------

def req_enum(data, key, choices):
    if not _present(data, key):
        invalid("Field '%s' is required." % key)
    return opt_enum(data, key, choices)


def opt_enum(data, key, choices, default=None):
    if not _present(data, key):
        return default
    value = data[key]
    if not isinstance(value, str) or value not in choices:
        invalid("Field '%s' must be one of %s." % (key, ", ".join(choices)))
    return value


# --------------------------------------------------------------------------
# numbers
# --------------------------------------------------------------------------

def req_int(data, key, low=None, high=None):
    if not _present(data, key):
        invalid("Field '%s' is required." % key)
    return opt_int(data, key, low, high)


def opt_int(data, key, low=None, high=None, default=None):
    if not _present(data, key):
        return default
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int):
        invalid("Field '%s' must be an integer." % key)
    if low is not None and value < low:
        invalid("Field '%s' must be at least %s." % (key, low))
    if high is not None and value > high:
        invalid("Field '%s' must be at most %s." % (key, high))
    return value


def req_num(data, key, low=None, high=None):
    if not _present(data, key):
        invalid("Field '%s' is required." % key)
    return opt_num(data, key, low, high)


def opt_num(data, key, low=None, high=None, default=None):
    if not _present(data, key):
        return default
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        invalid("Field '%s' must be a number." % key)
    number = dec(value)
    if low is not None and number < dec(low):
        invalid("Field '%s' must be at least %s." % (key, low))
    if high is not None and number > dec(high):
        invalid("Field '%s' must be at most %s." % (key, high))
    return number


def req_bool(data, key):
    if not _present(data, key):
        invalid("Field '%s' is required." % key)
    return opt_bool(data, key)


def opt_bool(data, key, default=None):
    if not _present(data, key):
        return default
    value = data[key]
    if not isinstance(value, bool):
        invalid("Field '%s' must be a boolean." % key)
    return value


# --------------------------------------------------------------------------
# instants, objects, arrays
# --------------------------------------------------------------------------

def req_dt(data, key):
    if not _present(data, key):
        invalid("Field '%s' is required." % key)
    return opt_dt(data, key)


def opt_dt(data, key, default=None):
    if not _present(data, key):
        return default
    value = data[key]
    parsed = parse_iso(value) if isinstance(value, str) else None
    if parsed is None:
        invalid("Field '%s' must be an ISO 8601 instant." % key)
    return parsed


def req_obj(data, key):
    if not _present(data, key):
        invalid("Field '%s' is required." % key)
    value = data[key]
    if not isinstance(value, dict):
        invalid("Field '%s' must be an object." % key)
    return value


def req_str_list(data, key, min_len=0):
    if not _present(data, key):
        invalid("Field '%s' is required." % key)
    value = data[key]
    if not isinstance(value, list):
        invalid("Field '%s' must be an array." % key)
    if len(value) < min_len:
        invalid("Field '%s' must contain at least %d entries." % (key, min_len))
    for item in value:
        if not isinstance(item, str) or item == "":
            invalid("Every entry of '%s' must be a non-empty string." % key)
    return list(value)


# --------------------------------------------------------------------------
# query string
# --------------------------------------------------------------------------

def _int_arg(name, default, low, high):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        invalid("Query parameter '%s' must be an integer." % name)
    value = int(text)
    if low is not None and value < low:
        invalid("Query parameter '%s' must be at least %d." % (name, low))
    if high is not None and value > high:
        invalid("Query parameter '%s' must be at most %d." % (name, high))
    return value


def pagination():
    limit = _int_arg("limit", 10, 1, 100)
    offset = _int_arg("offset", 0, 0, None)
    return limit, offset


def enum_filter(name, choices):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in choices:
        invalid("Query parameter '%s' must be one of %s." % (name, ", ".join(choices)))
    return raw


def str_filter(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw
