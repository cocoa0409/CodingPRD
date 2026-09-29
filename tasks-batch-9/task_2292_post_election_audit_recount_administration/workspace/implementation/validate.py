"""Tier-3 shape validation helpers.

Everything in this module raises ERR_VALIDATION only; no store reads happen
here so the validation tier ordering in PRD section 2.9 is preserved.
"""

from decimal import Decimal, InvalidOperation

from flask import request

from db import parse_date, parse_dt
from errors import fail

MISSING = object()

PAGINATION_LIMIT_DEFAULT = 10
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
PAGINATION_OFFSET_DEFAULT = 0
PAGINATION_OFFSET_MIN = 0


def body():
    """Return the JSON request body as a dict (empty dict when absent)."""
    raw = request.get_data()
    if raw is None or len(raw.strip()) == 0:
        return {}
    parsed = request.get_json(silent=True)
    if parsed is None:
        fail("ERR_VALIDATION", "Request body is not valid JSON.")
    if not isinstance(parsed, dict):
        fail("ERR_VALIDATION", "Request body must be a JSON object.")
    return parsed


def _present(data, key):
    return key in data and data[key] is not None


def req_str(data, key, min_len=1, max_len=None):
    if not _present(data, key):
        fail("ERR_VALIDATION", "Field '%s' is required." % key)
    return _check_str(data[key], key, min_len, max_len)


def opt_str(data, key, min_len=1, max_len=None, default=None, allow_null=True):
    if key not in data:
        return default
    if data[key] is None:
        if allow_null:
            return None
        fail("ERR_VALIDATION", "Field '%s' may not be null." % key)
    return _check_str(data[key], key, min_len, max_len)


def _check_str(value, key, min_len, max_len):
    if not isinstance(value, str):
        fail("ERR_VALIDATION", "Field '%s' must be a string." % key)
    if min_len is not None and len(value) < min_len:
        fail("ERR_VALIDATION", "Field '%s' is too short." % key)
    if max_len is not None and len(value) > max_len:
        fail("ERR_VALIDATION", "Field '%s' is too long." % key)
    return value


def req_int(data, key, min_value=None, max_value=None):
    if not _present(data, key):
        fail("ERR_VALIDATION", "Field '%s' is required." % key)
    return _check_int(data[key], key, min_value, max_value)


def opt_int(data, key, min_value=None, max_value=None, default=None):
    if key not in data or data[key] is None:
        return default
    return _check_int(data[key], key, min_value, max_value)


def _check_int(value, key, min_value, max_value):
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_VALIDATION", "Field '%s' must be an integer." % key)
    if min_value is not None and value < min_value:
        fail("ERR_VALIDATION", "Field '%s' is below the allowed minimum." % key)
    if max_value is not None and value > max_value:
        fail("ERR_VALIDATION", "Field '%s' is above the allowed maximum." % key)
    return value


def opt_num(data, key, min_value=None, max_value=None, default=None, max_dp=None):
    if key not in data or data[key] is None:
        return default
    return _check_num(data[key], key, min_value, max_value, max_dp)


def req_num(data, key, min_value=None, max_value=None, max_dp=None):
    if not _present(data, key):
        fail("ERR_VALIDATION", "Field '%s' is required." % key)
    return _check_num(data[key], key, min_value, max_value, max_dp)


def _check_num(value, key, min_value, max_value, max_dp):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_VALIDATION", "Field '%s' must be a number." % key)
    try:
        dec = Decimal(str(value))
    except InvalidOperation:
        fail("ERR_VALIDATION", "Field '%s' must be a number." % key)
    if not dec.is_finite():
        fail("ERR_VALIDATION", "Field '%s' must be a finite number." % key)
    if min_value is not None and dec < Decimal(str(min_value)):
        fail("ERR_VALIDATION", "Field '%s' is below the allowed minimum." % key)
    if max_value is not None and dec > Decimal(str(max_value)):
        fail("ERR_VALIDATION", "Field '%s' is above the allowed maximum." % key)
    if max_dp is not None:
        exponent = dec.normalize().as_tuple().exponent
        if isinstance(exponent, int) and exponent < -max_dp:
            fail(
                "ERR_VALIDATION",
                "Field '%s' allows at most %d decimal places." % (key, max_dp),
            )
    return dec


def req_bool(data, key):
    if not _present(data, key):
        fail("ERR_VALIDATION", "Field '%s' is required." % key)
    if not isinstance(data[key], bool):
        fail("ERR_VALIDATION", "Field '%s' must be a boolean." % key)
    return data[key]


def opt_bool(data, key, default=None):
    if key not in data or data[key] is None:
        return default
    if not isinstance(data[key], bool):
        fail("ERR_VALIDATION", "Field '%s' must be a boolean." % key)
    return data[key]


def req_enum(data, key, choices):
    value = req_str(data, key, 1, None)
    if value not in choices:
        fail("ERR_VALIDATION", "Field '%s' is not a recognized value." % key)
    return value


def opt_enum(data, key, choices, default=None):
    if key not in data or data[key] is None:
        return default
    value = _check_str(data[key], key, 1, None)
    if value not in choices:
        fail("ERR_VALIDATION", "Field '%s' is not a recognized value." % key)
    return value


def req_dt(data, key):
    value = req_str(data, key, 1, None)
    parsed = parse_dt(value)
    if parsed is None:
        fail("ERR_VALIDATION", "Field '%s' must be an ISO 8601 timestamp." % key)
    return parsed


def opt_dt(data, key, default=None):
    if key not in data or data[key] is None:
        return default
    value = _check_str(data[key], key, 1, None)
    parsed = parse_dt(value)
    if parsed is None:
        fail("ERR_VALIDATION", "Field '%s' must be an ISO 8601 timestamp." % key)
    return parsed


def req_date(data, key):
    value = req_str(data, key, 1, None)
    parsed = parse_date(value)
    if parsed is None:
        fail("ERR_VALIDATION", "Field '%s' must be a YYYY-MM-DD date." % key)
    return value, parsed


def req_list(data, key, min_len=1, max_len=None):
    if not _present(data, key):
        fail("ERR_VALIDATION", "Field '%s' is required." % key)
    return _check_list(data[key], key, min_len, max_len)


def opt_list(data, key, min_len=1, max_len=None, default=None):
    if key not in data or data[key] is None:
        return default
    return _check_list(data[key], key, min_len, max_len)


def _check_list(value, key, min_len, max_len):
    if not isinstance(value, list):
        fail("ERR_VALIDATION", "Field '%s' must be an array." % key)
    if min_len is not None and len(value) < min_len:
        fail("ERR_VALIDATION", "Field '%s' has too few entries." % key)
    if max_len is not None and len(value) > max_len:
        fail("ERR_VALIDATION", "Field '%s' has too many entries." % key)
    return value


def req_vote_map(data, key):
    if not _present(data, key):
        fail("ERR_VALIDATION", "Field '%s' is required." % key)
    return _check_vote_map(data[key], key)


def opt_vote_map(data, key, default=None):
    if key not in data or data[key] is None:
        return default
    return _check_vote_map(data[key], key)


def _check_vote_map(value, key):
    if not isinstance(value, dict):
        fail("ERR_VALIDATION", "Field '%s' must be an object." % key)
    out = {}
    for name, count in value.items():
        if not isinstance(name, str) or len(name) == 0:
            fail("ERR_VALIDATION", "Field '%s' has an invalid key." % key)
        if isinstance(count, bool) or not isinstance(count, int):
            fail("ERR_VALIDATION", "Field '%s' values must be integers." % key)
        if count < 0:
            fail("ERR_VALIDATION", "Field '%s' values must be zero or greater." % key)
        out[name] = count
    return out


def req_id_list(data, key, min_len=1):
    values = req_list(data, key, min_len=min_len)
    for item in values:
        if not isinstance(item, str) or len(item) == 0:
            fail("ERR_VALIDATION", "Field '%s' must contain non-empty strings." % key)
    return values


def req_digits(data, key, length):
    value = req_str(data, key, 1, None)
    if len(value) != length or not value.isdigit() or not value.isascii():
        fail(
            "ERR_VALIDATION",
            "Field '%s' must be exactly %d digits." % (key, length),
        )
    return value


# --------------------------------------------------------------------------
# query string
# --------------------------------------------------------------------------


def _query_int(name, default, min_value, max_value):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    negative = text.startswith("-")
    digits = text[1:] if negative or text.startswith("+") else text
    if not digits.isdigit():
        fail("ERR_VALIDATION", "Query parameter '%s' must be an integer." % name)
    value = int(text)
    if min_value is not None and value < min_value:
        fail("ERR_VALIDATION", "Query parameter '%s' is out of range." % name)
    if max_value is not None and value > max_value:
        fail("ERR_VALIDATION", "Query parameter '%s' is out of range." % name)
    return value


def pagination():
    limit = _query_int(
        "limit", PAGINATION_LIMIT_DEFAULT, PAGINATION_LIMIT_MIN, PAGINATION_LIMIT_MAX
    )
    offset = _query_int("offset", PAGINATION_OFFSET_DEFAULT, PAGINATION_OFFSET_MIN, None)
    return limit, offset


def filter_value(name, choices=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if choices is not None and raw not in choices:
        fail("ERR_VALIDATION", "Query parameter '%s' is not a recognized value." % name)
    return raw


def filter_bool(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw in ("true", "True"):
        return True
    if raw in ("false", "False"):
        return False
    fail("ERR_VALIDATION", "Query parameter '%s' must be a boolean." % name)
