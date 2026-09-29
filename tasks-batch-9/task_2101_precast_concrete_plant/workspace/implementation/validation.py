"""Body-schema validation (order of refusal step 5) and query parsing.

Every breach raises ERR_VALIDATION (400): missing required field, wrong type,
enum value outside its set, numeric outside its declared range, unparseable
ISO 8601 datetime, or an interval whose end is not after its start (PRD 2.8).
"""
import json
from decimal import Decimal, InvalidOperation

from flask import request

import constants
import db
import errors

_MISSING = object()


def _bad(msg):
    errors.fail(errors.ERR_VALIDATION, msg)


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


def req_text(body, field):
    """A free-text field: present and a string, empty allowed."""
    return req_str(body, field, min_len=0)


def req_bool(body, field):
    val = body.get(field, _MISSING)
    if val is _MISSING or val is None:
        _bad("Missing required field: %s." % field)
    if not isinstance(val, bool):
        _bad("Field %s must be a boolean." % field)
    return val


def req_int(body, field, minimum=None, maximum=None, exclusive_min=None):
    val = body.get(field, _MISSING)
    if val is _MISSING or val is None:
        _bad("Missing required field: %s." % field)
    if isinstance(val, bool) or not isinstance(val, int):
        _bad("Field %s must be an integer." % field)
    _range(field, Decimal(val), minimum, maximum, exclusive_min)
    return val


def req_number(body, field, minimum=None, maximum=None, exclusive_min=None):
    val = body.get(field, _MISSING)
    if val is _MISSING or val is None:
        _bad("Missing required field: %s." % field)
    return _as_decimal(field, val, minimum, maximum, exclusive_min)


def opt_number(body, field, minimum=None, maximum=None, exclusive_min=None):
    if not present(body, field):
        return None
    return _as_decimal(field, body[field], minimum, maximum, exclusive_min)


def _as_decimal(field, val, minimum=None, maximum=None, exclusive_min=None):
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
    _range(field, dec, minimum, maximum, exclusive_min)
    return dec


def _range(field, dec, minimum, maximum, exclusive_min):
    if exclusive_min is not None and dec <= Decimal(str(exclusive_min)):
        _bad("Field %s must be greater than %s." % (field, exclusive_min))
    if minimum is not None and dec < Decimal(str(minimum)):
        _bad("Field %s must be at least %s." % (field, minimum))
    if maximum is not None and dec > Decimal(str(maximum)):
        _bad("Field %s must be at most %s." % (field, maximum))


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


def req_decimal_choice(body, field, choices):
    """A numeric field restricted to a fixed set of decimal values."""
    val = body.get(field, _MISSING)
    if val is _MISSING or val is None:
        _bad("Missing required field: %s." % field)
    dec = _as_decimal(field, val)
    for choice in choices:
        if dec == choice:
            return choice
    _bad("Field %s must be one of %s." % (field, [str(c) for c in choices]))


def req_datetime(body, field):
    val = body.get(field, _MISSING)
    if val is _MISSING or val is None:
        _bad("Missing required field: %s." % field)
    if not isinstance(val, str):
        _bad("Field %s must be an ISO 8601 datetime string." % field)
    parsed = db.parse_iso8601(val)
    if parsed is None:
        _bad("Field %s must be a valid ISO 8601 datetime." % field)
    return parsed


def req_date(body, field):
    """An ISO 8601 calendar date, YYYY-MM-DD (PRD 3.2)."""
    val = req_str(body, field)
    parts = val.split("-")
    if len(parts) != 3 or len(parts[0]) != 4 or len(parts[1]) != 2 or len(parts[2]) != 2:
        _bad("Field %s must be an ISO 8601 date (YYYY-MM-DD)." % field)
    if db.parse_iso8601(val + "T00:00:00Z") is None:
        _bad("Field %s must be an ISO 8601 date (YYYY-MM-DD)." % field)
    return val


def req_id(body, field):
    return req_str(body, field)


def opt_id(body, field):
    if not present(body, field):
        return None
    return req_str(body, field)


def require_interval(start, end, start_field, end_field):
    if not end > start:
        _bad("Field %s must be after %s." % (end_field, start_field))


def pagination():
    """limit defaults to 10 (1..100); offset defaults to 0 (>= 0) - PRD 2.3."""
    args = request.args
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None or raw_limit == "":
        limit = constants.LIMIT_DEFAULT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            _bad("Query parameter limit must be an integer.")
        if limit < constants.LIMIT_MIN or limit > constants.LIMIT_MAX:
            _bad("Query parameter limit must be between %d and %d."
                 % (constants.LIMIT_MIN, constants.LIMIT_MAX))
    if raw_offset is None or raw_offset == "":
        offset = constants.OFFSET_DEFAULT
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            _bad("Query parameter offset must be an integer.")
        if offset < constants.OFFSET_MIN:
            _bad("Query parameter offset must be at least %d." % constants.OFFSET_MIN)
    return limit, offset


def query_filter(name):
    val = request.args.get(name)
    if val is None or val == "":
        return None
    return val
