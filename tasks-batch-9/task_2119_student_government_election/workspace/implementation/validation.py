"""Body-schema validation (ladder rule 5) and pagination (ladder rule 6).

Every schema breach raises ERR_INVALID_REQUEST (400): a missing required
field, a wrong type, an enum value outside its domain, a number outside its
declared range or an unparseable ISO 8601 instant.  Pagination breaches raise
ERR_INVALID_PAGINATION (400).
"""
import json
from decimal import Decimal, InvalidOperation

from flask import request

import constants
import db
import errors

_MISSING = object()


def _bad(msg):
    errors.fail(errors.ERR_INVALID_REQUEST, msg)


def get_body():
    """Parse the JSON body, keeping decimal literals exact."""
    raw = request.get_data(as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = json.loads(raw, parse_float=Decimal)
    except (ValueError, InvalidOperation):
        _bad("Request body must be valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        _bad("Request body must be a JSON object.")
    return parsed


def present(body, field):
    return field in body and body[field] is not None


def has_key(body, field):
    return field in body


# ---- strings ---------------------------------------------------------------
def req_str(body, field, min_len=1, max_len=None):
    val = body.get(field, _MISSING)
    if val is _MISSING or val is None:
        _bad("Missing required field: %s." % field)
    if not isinstance(val, str):
        _bad("Field %s must be a string." % field)
    if len(val) < min_len:
        _bad("Field %s must be at least %d characters." % (field, min_len))
    if max_len is not None and len(val) > max_len:
        _bad("Field %s must be at most %d characters." % (field, max_len))
    return val


def opt_str(body, field, default=None, min_len=1, max_len=None):
    if not present(body, field):
        return default
    return req_str(body, field, min_len=min_len, max_len=max_len)


def req_text(body, field):
    """Free text: present and a string; empty string accepted."""
    return req_str(body, field, min_len=0)


def opt_text(body, field, default=None):
    if not present(body, field):
        return default
    return req_str(body, field, min_len=0)


# ---- booleans --------------------------------------------------------------
def req_bool(body, field):
    val = body.get(field, _MISSING)
    if val is _MISSING or val is None:
        _bad("Missing required field: %s." % field)
    if not isinstance(val, bool):
        _bad("Field %s must be a boolean." % field)
    return val


def opt_bool(body, field, default=None):
    if not present(body, field):
        return default
    return req_bool(body, field)


# ---- integers --------------------------------------------------------------
def req_int(body, field, minimum=None, maximum=None):
    val = body.get(field, _MISSING)
    if val is _MISSING or val is None:
        _bad("Missing required field: %s." % field)
    if isinstance(val, bool) or not isinstance(val, int):
        _bad("Field %s must be an integer." % field)
    if minimum is not None and val < minimum:
        _bad("Field %s must be at least %s." % (field, minimum))
    if maximum is not None and val > maximum:
        _bad("Field %s must be at most %s." % (field, maximum))
    return val


def opt_int(body, field, default=None, minimum=None, maximum=None):
    if not present(body, field):
        return default
    return req_int(body, field, minimum=minimum, maximum=maximum)


# ---- decimals --------------------------------------------------------------
def _as_decimal(field, val, minimum=None, maximum=None):
    if isinstance(val, bool):
        _bad("Field %s must be a number." % field)
    if isinstance(val, int):
        dec = Decimal(val)
    elif isinstance(val, Decimal):
        dec = val
    elif isinstance(val, float):
        dec = Decimal(str(val))
    else:
        _bad("Field %s must be a number." % field)
    if not dec.is_finite():
        _bad("Field %s must be a finite number." % field)
    if minimum is not None and dec < Decimal(str(minimum)):
        _bad("Field %s must be at least %s." % (field, minimum))
    if maximum is not None and dec > Decimal(str(maximum)):
        _bad("Field %s must be at most %s." % (field, maximum))
    return dec


def req_decimal(body, field, minimum=None, maximum=None):
    val = body.get(field, _MISSING)
    if val is _MISSING or val is None:
        _bad("Missing required field: %s." % field)
    return _as_decimal(field, val, minimum, maximum)


def opt_decimal(body, field, default=None, minimum=None, maximum=None):
    if not present(body, field):
        return default if default is None else Decimal(str(default))
    return _as_decimal(field, body[field], minimum, maximum)


# ---- enums -----------------------------------------------------------------
def req_enum(body, field, allowed):
    val = body.get(field, _MISSING)
    if val is _MISSING or val is None:
        _bad("Missing required field: %s." % field)
    if val not in allowed:
        _bad("Field %s must be one of %s." % (field, list(allowed)))
    return val


def opt_enum(body, field, allowed, default=None):
    if not present(body, field):
        return default
    return req_enum(body, field, allowed)


# ---- instants --------------------------------------------------------------
def req_dt(body, field):
    val = body.get(field, _MISSING)
    if val is _MISSING or val is None:
        _bad("Missing required field: %s." % field)
    parsed = db.parse_iso8601(val)
    if parsed is None:
        _bad("Field %s must be an ISO 8601 UTC instant." % field)
    return parsed


def opt_dt(body, field, default=None):
    if not present(body, field):
        return default
    return req_dt(body, field)


# ---- arrays ----------------------------------------------------------------
def req_enum_array(body, field, allowed, non_empty=True):
    val = body.get(field, _MISSING)
    if val is _MISSING or val is None:
        _bad("Missing required field: %s." % field)
    if not isinstance(val, list):
        _bad("Field %s must be an array." % field)
    if non_empty and len(val) == 0:
        _bad("Field %s must not be empty." % field)
    for item in val:
        if item not in allowed:
            _bad("Field %s must be a subset of %s." % (field, list(allowed)))
    return list(val)


def req_object_array(body, field):
    val = body.get(field, _MISSING)
    if val is _MISSING or val is None:
        _bad("Missing required field: %s." % field)
    if not isinstance(val, list):
        _bad("Field %s must be an array." % field)
    for item in val:
        if not isinstance(item, dict):
            _bad("Every entry of %s must be an object." % field)
    return val


def reject_unexpected_null(body, field):
    """A field explicitly supplied as null where a value is required."""
    if field in body and body[field] is None:
        _bad("Field %s must not be null." % field)


# ---- pagination (ladder rule 6) --------------------------------------------
def _int_arg(raw):
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def pagination():
    args = request.args
    limit = constants.PAGE_LIMIT_DEFAULT
    offset = constants.PAGE_OFFSET_DEFAULT
    if "limit" in args:
        parsed = _int_arg(args.get("limit"))
        if parsed is None or parsed < constants.PAGE_LIMIT_MIN or parsed > constants.PAGE_LIMIT_MAX:
            errors.fail(errors.ERR_INVALID_PAGINATION,
                        "limit must be an integer between %d and %d."
                        % (constants.PAGE_LIMIT_MIN, constants.PAGE_LIMIT_MAX))
        limit = parsed
    if "offset" in args:
        parsed = _int_arg(args.get("offset"))
        if parsed is None or parsed < 0:
            errors.fail(errors.ERR_INVALID_PAGINATION,
                        "offset must be a non-negative integer.")
        offset = parsed
    return limit, offset
