"""Shared request-parsing, validation, and pagination helpers."""
from flask import request

import errors
from errors import ApiError
from timeutil import parse_iso

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def get_json_body():
    """Return the parsed JSON object body, or raise ERR_INVALID_REQUEST.

    A missing body is treated as an empty object so that required-field checks
    surface the precise field. A non-object JSON value is rejected.
    """
    if request.content_length in (None, 0) and not (request.data or b"").strip():
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "Request body must be valid JSON.")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "Request body must be a JSON object.")
    return data


def invalid(message):
    raise ApiError(errors.ERR_INVALID_REQUEST, 400, message)


def require_field(body, name):
    if name not in body or body[name] is None:
        invalid("Missing required field: %s" % name)
    return body[name]


def require_string(body, name, min_len=None):
    value = require_field(body, name)
    if not isinstance(value, str):
        invalid("Field %s must be a string." % name)
    if min_len is not None and len(value) < min_len:
        invalid("Field %s must be at least %d characters." % (name, min_len))
    return value


def require_enum(body, name, allowed):
    value = require_field(body, name)
    if not isinstance(value, str) or value not in allowed:
        invalid("Field %s must be one of %s." % (name, sorted(allowed)))
    return value


def require_number(body, name, minimum=None, maximum=None):
    value = require_field(body, name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        invalid("Field %s must be a number." % name)
    if minimum is not None and value < minimum:
        invalid("Field %s must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        invalid("Field %s must be <= %s." % (name, maximum))
    return value


def require_integer(body, name, minimum=None, maximum=None):
    value = require_field(body, name)
    if isinstance(value, bool) or not isinstance(value, int):
        invalid("Field %s must be an integer." % name)
    if minimum is not None and value < minimum:
        invalid("Field %s must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        invalid("Field %s must be <= %s." % (name, maximum))
    return value


def require_bool(body, name):
    value = require_field(body, name)
    if not isinstance(value, bool):
        invalid("Field %s must be a boolean." % name)
    return value


def require_iso_datetime(body, name):
    value = require_field(body, name)
    if not isinstance(value, str) or parse_iso(value) is None:
        invalid("Field %s must be a valid ISO 8601 datetime." % name)
    return value


def optional_integer(body, name, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        return None
    return require_integer(body, name, minimum=minimum, maximum=maximum)


def pagination_params():
    """Parse limit/offset query params per PRD §2.3.

    limit default 10, min 1, max 100; offset default 0. Out-of-range or
    malformed values yield ERR_INVALID_REQUEST.
    """
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None:
        limit = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            invalid("limit must be an integer.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            invalid("limit must be between %d and %d." % (PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT))

    if raw_offset is None:
        offset = PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            invalid("offset must be an integer.")
        if offset < 0:
            invalid("offset must be >= 0.")

    return limit, offset


def paginate(rows):
    """Sort by created_at asc, apply limit/offset; return (page, limit, offset, total)."""
    limit, offset = pagination_params()
    ordered = sorted(rows, key=lambda r: (r.get("created_at", ""), r.get("id", "")))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, limit, offset, total
