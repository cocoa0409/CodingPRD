"""Ladder priority 8 (field constraints) and 10 (intra-body consistency)."""
import re
from decimal import Decimal, InvalidOperation

from flask import request

from core import ApiError, dq, parse_dt

MISSING = object()


def bad(message):
    raise ApiError("ERR_VALIDATION", 422, message)


def inconsistent(message):
    raise ApiError("ERR_INCONSISTENT_TERMS", 422, message)


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        bad("request body must be a JSON object")
    return data


def present(data, name):
    return name in data and data[name] is not None


def string(data, name, required=True, min_len=1, max_len=None, pattern=None,
           default=MISSING):
    if not present(data, name):
        if required:
            bad("%s is required" % name)
        return None if default is MISSING else default
    value = data[name]
    if not isinstance(value, str):
        bad("%s must be a string" % name)
    if min_len is not None and len(value) < min_len:
        bad("%s is too short" % name)
    if max_len is not None and len(value) > max_len:
        bad("%s is too long" % name)
    if pattern is not None and not re.match(pattern, value):
        bad("%s has an invalid format" % name)
    return value


def enum(data, name, allowed, required=True, default=MISSING):
    if not present(data, name):
        if required:
            bad("%s is required" % name)
        return None if default is MISSING else default
    value = data[name]
    if not isinstance(value, str) or value not in allowed:
        bad("%s must be one of %s" % (name, ", ".join(allowed)))
    return value


def enum_list(data, name, allowed, required=True, default=MISSING,
              allow_empty=False, empty_error=None):
    if not present(data, name):
        if required:
            bad("%s is required" % name)
        return None if default is MISSING else default
    value = data[name]
    if not isinstance(value, list):
        bad("%s must be an array" % name)
    if not value and not allow_empty:
        if empty_error:
            raise ApiError(empty_error, 422, "%s must not be empty" % name)
        bad("%s must not be empty" % name)
    for element in value:
        if not isinstance(element, str) or element not in allowed:
            bad("%s contains an invalid element" % name)
    return value


def id_list(data, name, required=True, empty_error=None, default=MISSING):
    if not present(data, name):
        if required:
            bad("%s is required" % name)
        return None if default is MISSING else default
    value = data[name]
    if not isinstance(value, list):
        bad("%s must be an array" % name)
    for element in value:
        if not isinstance(element, str) or not element:
            bad("%s contains an invalid element" % name)
    return value


def boolean(data, name, required=False, default=MISSING):
    if not present(data, name):
        if required:
            bad("%s is required" % name)
        return None if default is MISSING else default
    value = data[name]
    if not isinstance(value, bool):
        bad("%s must be a boolean" % name)
    return value


def integer(data, name, required=True, minimum=None, maximum=None, default=MISSING):
    if not present(data, name):
        if required:
            bad("%s is required" % name)
        return None if default is MISSING else default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int):
        bad("%s must be an integer" % name)
    if minimum is not None and value < minimum:
        bad("%s is below its minimum" % name)
    if maximum is not None and value > maximum:
        bad("%s is above its maximum" % name)
    return value


def decimal(data, name, scale, required=True, minimum=None, maximum=None,
            exclusive_min=False, default=MISSING):
    if not present(data, name):
        if required:
            bad("%s is required" % name)
        return None if default is MISSING else default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        bad("%s must be a number" % name)
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        bad("%s must be a number" % name)
    if not parsed.is_finite():
        bad("%s must be a finite number" % name)
    exponent = parsed.as_tuple().exponent
    if isinstance(exponent, int) and -exponent > scale:
        bad("%s carries more than %d decimal places" % (name, scale))
    if minimum is not None:
        floor = Decimal(str(minimum))
        if exclusive_min and parsed <= floor:
            bad("%s must be strictly greater than %s" % (name, floor))
        if not exclusive_min and parsed < floor:
            bad("%s is below its minimum" % name)
    if maximum is not None and parsed > Decimal(str(maximum)):
        bad("%s is above its maximum" % name)
    return dq(parsed, scale)


def instant(data, name, required=True, default=MISSING):
    """An ISO-8601 instant or date. Returns (raw_text, datetime)."""
    if not present(data, name):
        if required:
            bad("%s is required" % name)
        return (None, None) if default is MISSING else default
    value = data[name]
    if not isinstance(value, str):
        bad("%s must be an ISO 8601 string" % name)
    parsed = parse_dt(value)
    if parsed is None:
        bad("%s is not a valid ISO 8601 instant" % name)
    return value, parsed


def fk(data, name, collection, error_id, required=True):
    """Priority 6: resolve a body foreign key, or defer to field validation."""
    from db import require
    if not present(data, name):
        if required:
            bad("%s is required" % name)
        return None
    value = data[name]
    if not isinstance(value, str) or not value:
        bad("%s must be a string id" % name)
    return require(collection, value, error_id)


def entity_id(data, name, required=True):
    if not present(data, name):
        if required:
            bad("%s is required" % name)
        return None
    value = data[name]
    if not isinstance(value, str) or not value:
        bad("%s must be a string id" % name)
    return value
