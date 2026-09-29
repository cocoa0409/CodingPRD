"""Rung 4 request-shape validation plus pagination and filter helpers."""
import json
from decimal import Decimal, InvalidOperation

from flask import request

from errors import fail
from response import (
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_DEFAULT_OFFSET,
    PAGINATION_MAX_LIMIT,
    PAGINATION_MIN_LIMIT,
)
from store import parse_date, parse_datetime

MISSING = object()

QUARTER = Decimal("0.25")


def read_body(allowed):
    raw = request.get_data(as_text=True)
    if raw is None or raw.strip() == "":
        body = {}
    else:
        try:
            body = json.loads(raw)
        except (ValueError, TypeError):
            fail("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
        if body is None:
            body = {}
    if not isinstance(body, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    for key in body.keys():
        if key not in allowed:
            fail("ERR_INVALID_REQUEST", "Unknown field '%s'." % key)
    return body


def _present(body, name):
    return name in body


def _missing(name):
    fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)


def _bad(name, why):
    fail("ERR_INVALID_REQUEST", "Field '%s' %s." % (name, why))


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_num(value):
    return (isinstance(value, int) or isinstance(value, float)) and not isinstance(value, bool)


# --------------------------------------------------------------------------
# strings
# --------------------------------------------------------------------------

def get_str(body, name, required=True, default=None, min_len=1, max_len=None,
            nullable=False):
    if not _present(body, name):
        if required:
            _missing(name)
        return default
    value = body[name]
    if value is None:
        if nullable:
            return None
        _bad(name, "must be a string")
    if not isinstance(value, str):
        _bad(name, "must be a string")
    if min_len is not None and len(value.strip()) < min_len:
        _bad(name, "must be a non-empty string")
    if max_len is not None and len(value) > max_len:
        _bad(name, "must be at most %d characters" % max_len)
    return value


def get_text(body, name, required=True, default=None):
    """Free narrative text: any string, blank permitted."""
    return get_str(body, name, required=required, default=default, min_len=None)


def get_id(body, name, required=True, default=None, nullable=False):
    return get_str(body, name, required=required, default=default, min_len=1,
                   nullable=nullable)


# --------------------------------------------------------------------------
# numbers
# --------------------------------------------------------------------------

def get_int(body, name, required=True, default=None, minimum=None, maximum=None):
    if not _present(body, name):
        if required:
            _missing(name)
        return default
    value = body[name]
    if not is_int(value):
        _bad(name, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(name, "must be at least %s" % minimum)
    if maximum is not None and value > maximum:
        _bad(name, "must be at most %s" % maximum)
    return value


def get_cents(body, name, required=True, default=None, minimum=0, maximum=None):
    """Monetary amounts must arrive as integer cents, never decimal strings."""
    if not _present(body, name):
        if required:
            _missing(name)
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(name, "must be supplied as integer cents")
    if minimum is not None and value < minimum:
        _bad(name, "must be at least %s" % minimum)
    if maximum is not None and value > maximum:
        _bad(name, "must be at most %s" % maximum)
    return value


def get_number(body, name, required=True, default=None, minimum=None, maximum=None,
               exclusive_min=None):
    if not _present(body, name):
        if required:
            _missing(name)
        return default
    value = body[name]
    if not is_num(value):
        _bad(name, "must be a number")
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        _bad(name, "must be a number")
    if exclusive_min is not None and dec <= Decimal(str(exclusive_min)):
        _bad(name, "must be greater than %s" % exclusive_min)
    if minimum is not None and dec < Decimal(str(minimum)):
        _bad(name, "must be at least %s" % minimum)
    if maximum is not None and dec > Decimal(str(maximum)):
        _bad(name, "must be at most %s" % maximum)
    return dec


def get_quarter_hours(body, name, required=True, default=None, minimum=None,
                      maximum=None, exclusive_min=None):
    dec = get_number(body, name, required=required, default=default,
                     minimum=minimum, maximum=maximum, exclusive_min=exclusive_min)
    if dec is None:
        return None
    if (dec / QUARTER) % 1 != 0:
        _bad(name, "must be an exact multiple of 0.25")
    return dec


def get_bool(body, name, required=False, default=None):
    if not _present(body, name):
        if required:
            _missing(name)
        return default
    value = body[name]
    if not isinstance(value, bool):
        _bad(name, "must be a boolean")
    return value


def get_enum(body, name, values, required=True, default=None):
    if not _present(body, name):
        if required:
            _missing(name)
        return default
    value = body[name]
    if not isinstance(value, str) or value not in values:
        _bad(name, "must be one of %s" % ", ".join(values))
    return value


def get_date(body, name, required=True, default=None, nullable=False):
    if not _present(body, name):
        if required:
            _missing(name)
        return default
    value = body[name]
    if value is None:
        if nullable:
            return None
        _bad(name, "must be an ISO 8601 calendar date")
    parsed = parse_date(value)
    if parsed is None:
        _bad(name, "must be an ISO 8601 calendar date (YYYY-MM-DD)")
    return parsed


def get_instant(body, name, required=True, default=None):
    if not _present(body, name):
        if required:
            _missing(name)
        return default
    value = body[name]
    parsed = parse_datetime(value)
    if parsed is None:
        _bad(name, "must be an ISO 8601 UTC date-time")
    return parsed


def get_str_array(body, name, required=True, default=None):
    if not _present(body, name):
        if required:
            _missing(name)
        return default
    value = body[name]
    if not isinstance(value, list):
        _bad(name, "must be an array")
    out = []
    for item in value:
        if not isinstance(item, str):
            _bad(name, "must be an array of strings")
        out.append(item)
    return out


def get_object_array(body, name, required=True, default=None):
    if not _present(body, name):
        if required:
            _missing(name)
        return list(default) if default is not None else None
    value = body[name]
    if not isinstance(value, list):
        _bad(name, "must be an array")
    for item in value:
        if not isinstance(item, dict):
            _bad(name, "must be an array of objects")
    return value


# --------------------------------------------------------------------------
# pagination and query filters
# --------------------------------------------------------------------------

def pagination():
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer.")
        if str(raw_limit).strip() != str(limit):
            fail("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "offset must be an integer.")
        if str(raw_offset).strip() != str(offset):
            fail("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset must be at least 0.")
    return limit, offset


def q_str(name):
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


def q_bool(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    low = value.strip().lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    fail("ERR_INVALID_REQUEST", "%s must be a boolean." % name)


def q_enum(name, values):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    if value not in values:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s." % (name, ", ".join(values)))
    return value
