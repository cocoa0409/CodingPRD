"""Rung-3 schema validation for request bodies and query strings.

Every failure raises ApiError("ERR_INVALID_REQUEST") -> 400.
"""
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError
from util import decimal_places, parse_iso

MISSING = object()


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body_json():
    """Parse the JSON body.  An absent or empty body is an empty object."""
    raw = request.get_data(cache=True, as_text=True) or ""
    if not raw.strip():
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        bad("Request body is not valid JSON.")
    if data is None:
        return {}
    if not isinstance(data, dict):
        bad("Request body must be a JSON object.")
    return data


def present(body, name):
    return name in body and body[name] is not None


# ------------------------------------------------------------------ strings ---

def field_str(body, name, required=True, min_len=1, max_len=None, default=None,
              allow_blank=False):
    if not present(body, name):
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % name)
    if not allow_blank and not value.strip():
        bad("Field '%s' must not be blank." % name)
    if min_len is not None and len(value) < min_len:
        bad("Field '%s' must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' must be at most %d characters." % (name, max_len))
    return value


def field_id(body, name, required=True, default=None):
    if not present(body, name):
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, str) or not value.strip():
        bad("Field '%s' must be a non-empty string identifier." % name)
    return value


def field_enum(body, name, allowed, required=True, default=None):
    if not present(body, name):
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        bad("Field '%s' must be one of %s." % (name, ", ".join(sorted(allowed))))
    return value


# ----------------------------------------------------------------- numerics ---

def field_int(body, name, required=True, minimum=None, maximum=None,
              exclusive_minimum=None, default=None):
    if not present(body, name):
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be at least %d." % (name, minimum))
    if exclusive_minimum is not None and value <= exclusive_minimum:
        bad("Field '%s' must be greater than %d." % (name, exclusive_minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be at most %d." % (name, maximum))
    return value


def field_number(body, name, required=True, minimum=None, maximum=None,
                 max_decimals=None, default=None):
    """Returns a Decimal for exact arithmetic, or the supplied default."""
    if not present(body, name):
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("Field '%s' must be a number." % name)
    try:
        dec = Decimal(repr(value)) if isinstance(value, float) else Decimal(value)
    except (InvalidOperation, ValueError):
        bad("Field '%s' must be a number." % name)
    if minimum is not None and dec < Decimal(str(minimum)):
        bad("Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and dec > Decimal(str(maximum)):
        bad("Field '%s' must be at most %s." % (name, maximum))
    if max_decimals is not None and decimal_places(dec) > max_decimals:
        bad("Field '%s' accepts at most %d decimal places." % (name, max_decimals))
    return dec


def field_bool(body, name, required=True, default=None):
    if not present(body, name):
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % name)
    return value


def field_datetime(body, name, required=True, default=None):
    """Returns (raw_string, aware datetime) or (default, None)."""
    if not present(body, name):
        if required:
            bad("Field '%s' is required." % name)
        return default, None
    value = body[name]
    if not isinstance(value, str):
        bad("Field '%s' must be an ISO 8601 datetime string." % name)
    parsed = parse_iso(value)
    if parsed is None:
        bad("Field '%s' must be an ISO 8601 datetime string." % name)
    return value, parsed


# -------------------------------------------------------------- query string --

def pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        if raw_limit.strip() == "":
            bad("Query parameter 'limit' must be an integer between 1 and 100.")
        try:
            limit = int(raw_limit.strip())
        except ValueError:
            bad("Query parameter 'limit' must be an integer between 1 and 100.")
        if limit < 1 or limit > 100:
            bad("Query parameter 'limit' must be between 1 and 100.")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        if raw_offset.strip() == "":
            bad("Query parameter 'offset' must be a non-negative integer.")
        try:
            offset = int(raw_offset.strip())
        except ValueError:
            bad("Query parameter 'offset' must be a non-negative integer.")
        if offset < 0:
            bad("Query parameter 'offset' must not be negative.")
    return limit, offset


def query_enum(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        bad("Query parameter '%s' must be one of %s." % (name, ", ".join(sorted(allowed))))
    return value


def query_bool(name):
    value = request.args.get(name)
    if value is None:
        return None
    if value == "true":
        return True
    if value == "false":
        return False
    bad("Query parameter '%s' must be 'true' or 'false'." % name)


def query_str(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value
