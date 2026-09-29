"""Band 3 of the rejection ladder: request shape (PRD 2.8).

Required fields present and non-blank, types correct, enum members known,
numeric ranges respected, arrays free of duplicates.  Every violation is
ERR_INVALID_REQUEST / 400.  Pagination violations are ERR_INVALID_PAGINATION.
"""
from decimal import Decimal

from flask import request

from errors import ApiError
from util import dec, parse_dt

MISSING = object()


def _bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    """The JSON body as a dict; a missing body reads as an empty object."""
    payload = request.get_json(silent=True)
    if payload is None:
        if request.data:
            _bad("Request body must be valid JSON.")
        return {}
    if not isinstance(payload, dict):
        _bad("Request body must be a JSON object.")
    return payload


def _present(data, key, required):
    if key not in data or data[key] is None:
        if required:
            _bad("Field '%s' is required." % key)
        return False
    return True


def get_str(data, key, required=True, min_len=1, max_len=None, default=None, blank_ok=False):
    if not _present(data, key, required):
        return default
    value = data[key]
    if not isinstance(value, str):
        _bad("Field '%s' must be a string." % key)
    if not blank_ok and not value.strip():
        _bad("Field '%s' must not be blank." % key)
    if min_len is not None and len(value) < min_len:
        _bad("Field '%s' is shorter than %d characters." % (key, min_len))
    if max_len is not None and len(value) > max_len:
        _bad("Field '%s' is longer than %d characters." % (key, max_len))
    return value


def get_enum(data, key, members, required=True, default=None):
    if not _present(data, key, required):
        return default
    value = data[key]
    if not isinstance(value, str):
        _bad("Field '%s' must be a string." % key)
    if value not in members:
        _bad("Field '%s' must be one of %s." % (key, ", ".join(members)))
    return value


def get_int(data, key, required=True, minimum=None, maximum=None, default=None):
    if not _present(data, key, required):
        return default
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int):
        _bad("Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        _bad("Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and value > maximum:
        _bad("Field '%s' must be <= %s." % (key, maximum))
    return value


def get_number(
    data,
    key,
    required=True,
    minimum=None,
    maximum=None,
    exclusive_min=False,
    max_decimals=None,
    default=None,
):
    if not _present(data, key, required):
        return default
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad("Field '%s' must be a number." % key)
    number = dec(value)
    if number is None:
        _bad("Field '%s' must be a number." % key)
    if max_decimals is not None:
        exponent = number.normalize().as_tuple().exponent
        if isinstance(exponent, int) and exponent < -max_decimals:
            _bad("Field '%s' carries more than %d decimal places." % (key, max_decimals))
    if minimum is not None:
        if exclusive_min and number <= dec(minimum):
            _bad("Field '%s' must be greater than %s." % (key, minimum))
        if not exclusive_min and number < dec(minimum):
            _bad("Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and number > dec(maximum):
        _bad("Field '%s' must be <= %s." % (key, maximum))
    return number


def get_bool(data, key, required=True, default=None):
    if not _present(data, key, required):
        return default
    value = data[key]
    if not isinstance(value, bool):
        _bad("Field '%s' must be a boolean." % key)
    return value


def get_datetime(data, key, required=True, default=(None, None)):
    """Returns (raw_string, parsed_datetime).  Client instants echo back verbatim."""
    if not _present(data, key, required):
        return default
    value = data[key]
    if not isinstance(value, str):
        _bad("Field '%s' must be an ISO 8601 timestamp string." % key)
    parsed = parse_dt(value)
    if parsed is None:
        _bad("Field '%s' must be a valid ISO 8601 timestamp." % key)
    return value, parsed


def get_enum_array(
    data, key, members, required=True, min_len=0, max_len=None, allow_duplicates=False, default=None
):
    if not _present(data, key, required):
        return default if default is not None else None
    value = data[key]
    if not isinstance(value, list):
        _bad("Field '%s' must be an array." % key)
    for item in value:
        if not isinstance(item, str):
            _bad("Field '%s' must contain only strings." % key)
        if item not in members:
            _bad("Field '%s' contains an unknown member '%s'." % (key, item))
    if not allow_duplicates and len(set(value)) != len(value):
        _bad("Field '%s' must not contain duplicates." % key)
    if min_len is not None and len(value) < min_len:
        _bad("Field '%s' must hold at least %d members." % (key, min_len))
    if max_len is not None and len(value) > max_len:
        _bad("Field '%s' must hold at most %d members." % (key, max_len))
    return list(value)


def get_str_array(
    data, key, required=True, min_len=0, max_len=None, allow_duplicates=False, default=None
):
    if not _present(data, key, required):
        return default if default is not None else None
    value = data[key]
    if not isinstance(value, list):
        _bad("Field '%s' must be an array." % key)
    for item in value:
        if not isinstance(item, str):
            _bad("Field '%s' must contain only strings." % key)
    if not allow_duplicates and len(set(value)) != len(value):
        _bad("Field '%s' must not contain duplicates." % key)
    if min_len is not None and len(value) < min_len:
        _bad("Field '%s' must hold at least %d members." % (key, min_len))
    if max_len is not None and len(value) > max_len:
        _bad("Field '%s' must hold at most %d members." % (key, max_len))
    return list(value)


def pagination():
    """PRD 2.3: limit defaults to 10 (1..100), offset defaults to 0 (>= 0)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(str(limit_raw).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_PAGINATION")
    if offset_raw is not None:
        try:
            offset = int(str(offset_raw).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION")
        if offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION")
    return limit, offset
