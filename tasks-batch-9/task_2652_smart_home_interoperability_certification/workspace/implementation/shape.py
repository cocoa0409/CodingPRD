"""Request shape / range validators (rung 6) and enum membership (rung 7)."""

from flask import request

from db import parse_dt
from errors import ApiError

MISSING = object()


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body_obj():
    data = request.get_json(silent=True)
    if data is None:
        if request.get_data(as_text=True).strip():
            bad("request body must be a JSON object")
        return {}
    if not isinstance(data, dict):
        bad("request body must be a JSON object")
    return data


def present(body, key):
    return key in body and body.get(key) is not None


def req_str(body, key, min_len=1, max_len=None):
    value = body.get(key, MISSING)
    if value is MISSING or value is None:
        bad("%s is required" % key)
    if not isinstance(value, str):
        bad("%s must be a string" % key)
    if len(value) < min_len:
        bad("%s must be at least %d characters" % (key, min_len))
    if max_len is not None and len(value) > max_len:
        bad("%s must be at most %d characters" % (key, max_len))
    return value


def opt_str(body, key, min_len=1, max_len=None, default=None):
    if key not in body or body.get(key) is None:
        return default
    return req_str(body, key, min_len, max_len)


def req_int(body, key, lo=None, hi=None):
    value = body.get(key, MISSING)
    if value is MISSING or value is None:
        bad("%s is required" % key)
    if isinstance(value, bool) or not isinstance(value, int):
        bad("%s must be an integer" % key)
    if lo is not None and value < lo:
        bad("%s must be at least %d" % (key, lo))
    if hi is not None and value > hi:
        bad("%s must be at most %d" % (key, hi))
    return value


def opt_int(body, key, lo=None, hi=None, default=None):
    if key not in body or body.get(key) is None:
        return default
    return req_int(body, key, lo, hi)


def req_bool(body, key):
    value = body.get(key, MISSING)
    if value is MISSING or value is None:
        bad("%s is required" % key)
    if not isinstance(value, bool):
        bad("%s must be a boolean" % key)
    return value


def req_dt(body, key):
    raw = req_str(body, key)
    value = parse_dt(raw)
    if value is None:
        bad("%s must be an ISO 8601 timestamp" % key)
    return value


def opt_dt(body, key, default=None):
    if key not in body or body.get(key) is None:
        return default
    return req_dt(body, key)


def req_str_array(body, key, allow_empty=False, item_max_len=None):
    value = body.get(key, MISSING)
    if value is MISSING or value is None:
        bad("%s is required" % key)
    if not isinstance(value, list):
        bad("%s must be an array" % key)
    if not allow_empty and len(value) == 0:
        bad("%s must not be empty" % key)
    for item in value:
        if not isinstance(item, str) or not item:
            bad("%s must contain non-empty strings" % key)
        if item_max_len is not None and len(item) > item_max_len:
            bad("%s entries must be at most %d characters" % (key, item_max_len))
    if len(set(value)) != len(value):
        bad("%s must not contain duplicates" % key)
    return value


def check_enum(value, allowed, field):
    if value not in allowed:
        raise ApiError("ERR_INVALID_ENUM_VALUE", "%s must be one of %s" % (field, sorted(allowed)))
    return value


# ------------------------------------------------------------------ paging

def paging():
    """Rung 6 for list endpoints: limit 1..100 (default 10), offset >= 0 (default 0)."""
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        limit = _query_int("limit", raw_limit)
        if limit < 1 or limit > 100:
            bad("limit must be between 1 and 100")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        offset = _query_int("offset", raw_offset)
        if offset < 0:
            bad("offset must be at least 0")
    return limit, offset


def _query_int(name, raw):
    text = raw.strip()
    if not text:
        bad("%s must be an integer" % name)
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        bad("%s must be an integer" % name)
    return -int(digits) if negative else int(digits)


def q_str(name):
    value = request.args.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def q_bool(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    text = raw.strip().lower()
    if text == "true":
        return True
    if text == "false":
        return False
    bad("%s must be true or false" % name)


def q_enum(name, allowed):
    value = q_str(name)
    if value is None:
        return None
    return check_enum(value, allowed, name)
