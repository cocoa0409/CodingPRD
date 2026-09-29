"""Request shape validation (PRD 2.6 priority 3 -> ERR_INVALID_REQUEST).

Required fields present, types correct, enumerated values in range, integers
within their declared bounds, monetary amounts as integer counts of cents and
never as decimal strings, decimal fields within their declared scale, arrays
non-empty and free of duplicates, pagination within range.
"""

from decimal import Decimal, InvalidOperation

from flask import request

import logical_clock
from errors import ApiError

MAX_LIMIT = 100
MIN_LIMIT = 1
DEFAULT_LIMIT = 10
DEFAULT_OFFSET = 0


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def get_body():
    if request.data and request.data.strip():
        payload = request.get_json(silent=True)
        if payload is None:
            bad("Request body is not valid JSON.")
        if not isinstance(payload, dict):
            bad("Request body must be a JSON object.")
        return payload
    return {}


def present(body, key):
    return key in body and body[key] is not None


def _require(body, key, required):
    if present(body, key):
        return True
    if required:
        bad("Field %r is required." % key)
    return False


def str_field(body, key, required=True, allow_empty=False):
    if not _require(body, key, required):
        return None
    value = body[key]
    if not isinstance(value, str):
        bad("Field %r must be a string." % key)
    if not allow_empty and not value.strip():
        bad("Field %r must not be empty." % key)
    return value


def int_field(body, key, required=True, lo=None, hi=None):
    if not _require(body, key, required):
        return None
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field %r must be an integer." % key)
    if lo is not None and value < lo:
        bad("Field %r must be at least %s." % (key, lo))
    if hi is not None and value > hi:
        bad("Field %r must be at most %s." % (key, hi))
    return value


def money_field(body, key, required=True, minimum=0, strictly_positive=False):
    """Monetary amounts are integer counts of cents; a decimal number or a
    string is a malformed request (PRD 2.8)."""
    if not _require(body, key, required):
        return None
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field %r must be an integer count of cents." % key)
    if strictly_positive and value <= 0:
        bad("Field %r must be strictly positive." % key)
    if minimum is not None and value < minimum:
        bad("Field %r must be at least %s cents." % (key, minimum))
    return value


def num_field(
    body,
    key,
    required=True,
    scale=None,
    minimum=None,
    maximum=None,
    strictly_positive=False,
):
    if not _require(body, key, required):
        return None
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("Field %r must be a number." % key)
    try:
        dec = Decimal(str(value))
    except InvalidOperation:
        bad("Field %r must be a number." % key)
    if dec != dec or dec.is_infinite():
        bad("Field %r must be a finite number." % key)
    if scale is not None and -dec.as_tuple().exponent > scale:
        bad("Field %r carries more than %d decimal places." % (key, scale))
    if strictly_positive and dec <= 0:
        bad("Field %r must be strictly positive." % key)
    if minimum is not None and dec < Decimal(str(minimum)):
        bad("Field %r must be at least %s." % (key, minimum))
    if maximum is not None and dec > Decimal(str(maximum)):
        bad("Field %r must be at most %s." % (key, maximum))
    return dec


def bool_field(body, key, required=True):
    if not _require(body, key, required):
        return None
    value = body[key]
    if not isinstance(value, bool):
        bad("Field %r must be a boolean." % key)
    return value


def enum_field(body, key, allowed, required=True):
    if not _require(body, key, required):
        return None
    value = body[key]
    if not isinstance(value, str) or value not in allowed:
        bad("Field %r must be one of %s." % (key, ", ".join(allowed)))
    return value


def date_field(body, key, required=True):
    if not _require(body, key, required):
        return None
    value = body[key]
    if not isinstance(value, str):
        bad("Field %r must be an ISO calendar date." % key)
    try:
        return logical_clock.parse_day(value)
    except ValueError:
        bad("Field %r must be an ISO calendar date (YYYY-MM-DD)." % key)


def datetime_field(body, key, required=True):
    if not _require(body, key, required):
        return None
    value = body[key]
    if not isinstance(value, str):
        bad("Field %r must be an ISO 8601 UTC instant." % key)
    try:
        return logical_clock.parse_instant(value)
    except ValueError:
        bad("Field %r must be an ISO 8601 UTC instant." % key)


def id_list_field(body, key, min_len, max_len, required=True):
    if not _require(body, key, required):
        return None
    value = body[key]
    if not isinstance(value, list):
        bad("Field %r must be an array." % key)
    if len(value) < min_len:
        bad("Field %r must hold at least %d element(s)." % (key, min_len))
    if len(value) > max_len:
        bad("Field %r must hold at most %d element(s)." % (key, max_len))
    for element in value:
        if not isinstance(element, str) or not element.strip():
            bad("Field %r must hold non-empty string identifiers." % key)
    if len(set(value)) != len(value):
        bad("Field %r must not contain duplicates." % key)
    return list(value)


# --- query parameters -----------------------------------------------------

def pagination():
    limit = DEFAULT_LIMIT
    offset = DEFAULT_OFFSET
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            bad("limit must be an integer.")
        if str(raw_limit).strip() != str(limit):
            bad("limit must be an integer.")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            bad("limit must be between %d and %d." % (MIN_LIMIT, MAX_LIMIT))
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            bad("offset must be an integer.")
        if str(raw_offset).strip() != str(offset):
            bad("offset must be an integer.")
        if offset < 0:
            bad("offset must not be negative.")
    return limit, offset


def enum_filter(key, allowed):
    raw = request.args.get(key)
    if raw is None:
        return None
    if raw not in allowed:
        bad("%s=%r is not a recognised value." % (key, raw))
    return raw


def int_filter(key):
    raw = request.args.get(key)
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        bad("%s must be an integer." % key)
    if str(raw).strip() != str(value):
        bad("%s must be an integer." % key)
    return value


def str_filter(key):
    raw = request.args.get(key)
    if raw is None or raw == "":
        return None
    return raw
