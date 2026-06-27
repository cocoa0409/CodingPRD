"""Request body parsing, structural validation, and pagination helpers.

All structural failures raise ERR_INVALID_REQUEST (HTTP 422) per PRD §2.6.
"""
from flask import request

from errors import ApiError, ERR_INVALID_REQUEST
from clock import parse_iso


def get_json_body():
    """Return the parsed JSON object, or {} for an empty body.

    A body that is present but not a JSON object is malformed -> 422.
    """
    if request.content_length in (None, 0):
        data = request.get_json(silent=True)
        if data is None:
            return {}
    else:
        data = request.get_json(silent=True)
        if data is None:
            raise ApiError(ERR_INVALID_REQUEST, 422, "Request body must be valid JSON")
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, 422, "Request body must be a JSON object")
    return data


def invalid(msg):
    raise ApiError(ERR_INVALID_REQUEST, 422, msg)


def require(body, field):
    if field not in body or body[field] is None:
        invalid("Missing required field: %s" % field)
    return body[field]


def as_str(value, field, allow_empty=True):
    if not isinstance(value, str):
        invalid("Field %s must be a string" % field)
    if not allow_empty and value == "":
        invalid("Field %s must be a non-empty string" % field)
    return value


def as_int(value, field):
    # bool is a subclass of int in Python; reject it explicitly
    if isinstance(value, bool) or not isinstance(value, int):
        invalid("Field %s must be an integer" % field)
    return value


def as_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        invalid("Field %s must be a number" % field)
    return value


def as_bool(value, field):
    if not isinstance(value, bool):
        invalid("Field %s must be a boolean" % field)
    return value


def as_enum(value, field, allowed):
    if not isinstance(value, str) or value not in allowed:
        invalid("Field %s must be one of %s" % (field, sorted(allowed)))
    return value


def as_datetime(value, field):
    if not isinstance(value, str):
        invalid("Field %s must be an ISO-8601 datetime string" % field)
    try:
        return parse_iso(value)
    except (ValueError, TypeError):
        invalid("Field %s must be a valid ISO-8601 datetime" % field)


def parse_pagination():
    """limit default 10, min 1, max 100; offset default 0, min 0.

    Out-of-range / non-integer pagination params are malformed -> 422.
    """
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            invalid("limit must be an integer")
        if limit < 1 or limit > 100:
            invalid("limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            invalid("offset must be an integer")
        if offset < 0:
            invalid("offset must be >= 0")
    return limit, offset
