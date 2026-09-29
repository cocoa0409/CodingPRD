"""Ladder stage 3: request shape.  Everything here answers ERR_INVALID_REQUEST.

PRD 2.11 stage 3: the body parses, every required input field is present and
non-null, every field carries its declared JSON type, every enum-typed field
carries a declared member, integers are integers, decimals carry at most two
fractional digits, datetimes are RFC 3339 UTC with a trailing Z, and every
declared numeric range holds.
"""
import re
from decimal import Decimal

from flask import request

from common import fail, parse_dt


def bad(msg):
    fail("ERR_INVALID_REQUEST", msg)


def present(payload, field):
    if field not in payload or payload[field] is None:
        bad("field '%s' is required and may not be null" % field)
    return payload[field]


def opt(payload, field, default=None):
    if field not in payload or payload[field] is None:
        return default
    return payload[field]


def want_string(payload, field, required=True, default=None, min_len=None, max_len=None):
    if field not in payload or payload[field] is None:
        if required:
            bad("field '%s' is required and may not be null" % field)
        return default
    value = payload[field]
    if not isinstance(value, str):
        bad("field '%s' must be a string" % field)
    if min_len is not None and len(value) < min_len:
        bad("field '%s' must be at least %d characters" % (field, min_len))
    if max_len is not None and len(value) > max_len:
        bad("field '%s' must be at most %d characters" % (field, max_len))
    return value


def want_bool(payload, field, required=False, default=None):
    if field not in payload or payload[field] is None:
        if required:
            bad("field '%s' is required and may not be null" % field)
        return default
    value = payload[field]
    if not isinstance(value, bool):
        bad("field '%s' must be a boolean" % field)
    return value


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def want_int(payload, field, required=True, default=None, minimum=None, maximum=None,
             choices=None):
    if field not in payload or payload[field] is None:
        if required:
            bad("field '%s' is required and may not be null" % field)
        return default
    value = payload[field]
    if not is_int(value):
        bad("field '%s' must be an integer" % field)
    if minimum is not None and value < minimum:
        bad("field '%s' must be at least %s" % (field, minimum))
    if maximum is not None and value > maximum:
        bad("field '%s' must be at most %s" % (field, maximum))
    if choices is not None and value not in choices:
        bad("field '%s' must be one of %s" % (field, list(choices)))
    return value


def want_decimal(payload, field, required=True, default=None, minimum=None,
                 maximum=None, exclusive_min=None, exact_scale=None):
    """A decimal input: at most two fractional digits (PRD 2.6)."""
    if field not in payload or payload[field] is None:
        if required:
            bad("field '%s' is required and may not be null" % field)
        return default
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        bad("field '%s' must be a decimal number" % field)
    value = Decimal(value)
    exponent = value.as_tuple().exponent
    scale = -exponent if isinstance(exponent, int) and exponent < 0 else 0
    if scale > 2:
        bad("field '%s' may carry at most two fractional digits" % field)
    if exact_scale is not None and scale != exact_scale:
        bad("field '%s' must carry exactly %d fractional digits" % (field, exact_scale))
    if minimum is not None and value < minimum:
        bad("field '%s' must be at least %s" % (field, minimum))
    if exclusive_min is not None and value <= exclusive_min:
        bad("field '%s' must be greater than %s" % (field, exclusive_min))
    if maximum is not None and value > maximum:
        bad("field '%s' must be at most %s" % (field, maximum))
    return value


def want_enum(payload, field, members, required=True, default=None):
    if field not in payload or payload[field] is None:
        if required:
            bad("field '%s' is required and may not be null" % field)
        return default
    value = payload[field]
    if not isinstance(value, str) or value not in members:
        bad("field '%s' must be one of %s" % (field, list(members)))
    return value


def want_datetime(payload, field, required=True, default=None):
    """Returns (raw_string, datetime).  RFC 3339 UTC with a trailing Z."""
    if field not in payload or payload[field] is None:
        if required:
            bad("field '%s' is required and may not be null" % field)
        return (default, None)
    value = payload[field]
    parsed = parse_dt(value)
    if parsed is None:
        bad("field '%s' must be an RFC 3339 UTC timestamp ending in Z" % field)
    return (value, parsed)


def want_enum_array(payload, field, members, required=False, default=None,
                    allow_duplicates=True):
    if field not in payload or payload[field] is None:
        if required:
            bad("field '%s' is required and may not be null" % field)
        return list(default) if default is not None else None
    value = payload[field]
    if not isinstance(value, list):
        bad("field '%s' must be an array" % field)
    for item in value:
        if not isinstance(item, str) or item not in members:
            bad("field '%s' entries must be one of %s" % (field, list(members)))
    if not allow_duplicates and len(set(value)) != len(value):
        bad("field '%s' may not carry duplicate entries" % field)
    return list(value)


def want_object(payload, field, required=True, default=None):
    if field not in payload or payload[field] is None:
        if required:
            bad("field '%s' is required and may not be null" % field)
        return default
    value = payload[field]
    if not isinstance(value, dict):
        bad("field '%s' must be an object" % field)
    return value


def want_item_scores(payload, field, required=True):
    """The item_scores shape: object keyed by behaviour code whose value is an
    integer or the literal string "NA"."""
    if field not in payload or payload[field] is None:
        if required:
            bad("field '%s' is required and may not be null" % field)
        return None
    value = payload[field]
    if not isinstance(value, dict):
        bad("field '%s' must be an object keyed by behaviour code" % field)
    for key, item in value.items():
        if item is None:
            bad("field '%s' carries a null value for '%s'" % (field, key))
        if isinstance(item, str):
            if item != "NA":
                bad("field '%s' value for '%s' must be an integer or the literal \"NA\""
                    % (field, key))
        elif not is_int(item):
            bad("field '%s' value for '%s' must be an integer or the literal \"NA\""
                % (field, key))
    return dict(value)


# --------------------------------------------------------------------------
# Pagination (PRD 2.3)
# --------------------------------------------------------------------------

def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        if not re.fullmatch(r"-?\d+", raw or ""):
            bad("limit must be an integer between 1 and 100")
        limit = int(raw)
        if limit < 1 or limit > 100:
            bad("limit must be an integer between 1 and 100")
    if "offset" in args:
        raw = args.get("offset")
        if not re.fullmatch(r"-?\d+", raw or ""):
            bad("offset must be a non-negative integer")
        offset = int(raw)
        if offset < 0:
            bad("offset must be a non-negative integer")
    return limit, offset


def query_enum(name, members):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in members:
        bad("query parameter '%s' must be one of %s" % (name, list(members)))
    return value


def query_bool(name):
    value = request.args.get(name)
    if value is None:
        return None
    if value == "true":
        return True
    if value == "false":
        return False
    bad("query parameter '%s' must be true or false" % name)


def query_str(name):
    return request.args.get(name)
