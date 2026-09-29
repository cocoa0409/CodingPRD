"""Request-shape validation (global validation step 4, PRD 2.10)."""

from decimal import Decimal, InvalidOperation

from flask import request

import db
import errors
from errors import ERR_INVALID_REQUEST, fail

_MISSING = object()

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        fail(ERR_INVALID_REQUEST, "Request body is not valid JSON.")
    if not isinstance(payload, dict):
        fail(ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    return payload


def _present(data, key):
    return key in data and data[key] is not None


def req_str(data, key, min_len=None, max_len=None):
    if not _present(data, key):
        fail(ERR_INVALID_REQUEST, "Field '%s' is required." % key)
    value = data[key]
    if not isinstance(value, str):
        fail(ERR_INVALID_REQUEST, "Field '%s' must be a string." % key)
    if min_len is not None and len(value) < min_len:
        fail(ERR_INVALID_REQUEST, "Field '%s' is too short." % key)
    if max_len is not None and len(value) > max_len:
        fail(ERR_INVALID_REQUEST, "Field '%s' is too long." % key)
    return value


def opt_str(data, key, default=None, min_len=None, max_len=None):
    if not _present(data, key):
        return default
    return req_str(data, key, min_len, max_len)


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def req_int(data, key, min_v=None, max_v=None):
    if not _present(data, key):
        fail(ERR_INVALID_REQUEST, "Field '%s' is required." % key)
    value = data[key]
    if not _is_int(value):
        fail(ERR_INVALID_REQUEST, "Field '%s' must be an integer." % key)
    if min_v is not None and value < min_v:
        fail(ERR_INVALID_REQUEST, "Field '%s' is below its minimum." % key)
    if max_v is not None and value > max_v:
        fail(ERR_INVALID_REQUEST, "Field '%s' is above its maximum." % key)
    return value


def opt_int(data, key, default=None, min_v=None, max_v=None):
    if not _present(data, key):
        return default
    return req_int(data, key, min_v, max_v)


def req_enum(data, key, allowed):
    value = req_str(data, key)
    if value not in allowed:
        fail(ERR_INVALID_REQUEST, "Field '%s' is not a declared member." % key)
    return value


def opt_enum(data, key, allowed, default=None):
    if not _present(data, key):
        return default
    return req_enum(data, key, allowed)


def req_pct(data, key, decimals=4, min_v="0", max_v="1", max_inclusive=False):
    """Percentage field: at most `decimals` decimals, inside its range."""
    if not _present(data, key):
        fail(ERR_INVALID_REQUEST, "Field '%s' is required." % key)
    return _pct_value(data[key], key, decimals, min_v, max_v, max_inclusive)


def opt_pct(data, key, default, decimals=4, min_v="0", max_v="1",
            max_inclusive=False):
    if not _present(data, key):
        return Decimal(default).quantize(Decimal(1).scaleb(-decimals))
    return _pct_value(data[key], key, decimals, min_v, max_v, max_inclusive)


def _pct_value(value, key, decimals, min_v, max_v, max_inclusive):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail(ERR_INVALID_REQUEST, "Field '%s' must be a number." % key)
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        fail(ERR_INVALID_REQUEST, "Field '%s' must be a number." % key)
    exponent = dec.as_tuple().exponent
    if not isinstance(exponent, int) or exponent < -decimals:
        fail(ERR_INVALID_REQUEST,
             "Field '%s' carries more than %d decimals." % (key, decimals))
    low = Decimal(min_v)
    high = Decimal(max_v)
    if dec < low:
        fail(ERR_INVALID_REQUEST, "Field '%s' is below its minimum." % key)
    if max_inclusive:
        if dec > high:
            fail(ERR_INVALID_REQUEST, "Field '%s' is above its maximum." % key)
    else:
        if dec >= high:
            fail(ERR_INVALID_REQUEST, "Field '%s' is above its maximum." % key)
    return dec.quantize(Decimal(1).scaleb(-decimals))


def req_date(data, key):
    text = req_str(data, key)
    parsed = db.parse_iso_date(text)
    if parsed is None:
        fail(ERR_INVALID_REQUEST, "Field '%s' is not an ISO 8601 date." % key)
    return text, parsed


def req_id(data, key):
    if not _present(data, key):
        fail(ERR_INVALID_REQUEST, "Field '%s' is required." % key)
    value = data[key]
    if not isinstance(value, str) or not value:
        fail(ERR_INVALID_REQUEST, "Field '%s' must be a string id." % key)
    return value


# ------------------------------------------------------------------ query args
def pagination():
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        limit = _query_int("limit", raw_limit)
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            fail(ERR_INVALID_REQUEST, "limit must be between 1 and 100.")
    if raw_offset is not None:
        offset = _query_int("offset", raw_offset)
        if offset < 0:
            fail(ERR_INVALID_REQUEST, "offset must be at least 0.")
    return limit, offset


def _query_int(name, raw):
    text = raw.strip()
    if not text:
        fail(ERR_INVALID_REQUEST, "%s must be an integer." % name)
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        fail(ERR_INVALID_REQUEST, "%s must be an integer." % name)
    return -int(digits) if negative else int(digits)


def q_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw not in allowed:
        fail(ERR_INVALID_REQUEST, "%s is not a declared member." % name)
    return raw


def q_str(name):
    return request.args.get(name)
