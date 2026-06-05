"""Input parsing / field-level validation helpers.

All failures raise ApiError(ERR_VALIDATION, 400).
"""
import errors


def get_body():
    from flask import request
    if request.is_json:
        body = request.get_json(silent=True)
    else:
        # Accept empty body for action endpoints with no payload.
        raw = request.get_data(as_text=True)
        if not raw or not raw.strip():
            return {}
        body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.validation("Request body must be a JSON object.")
    return body


def require_string(body, key):
    if key not in body:
        raise errors.validation("Missing required field: %s" % key)
    value = body[key]
    if not isinstance(value, str) or value == "":
        raise errors.validation("Field %s must be a non-empty string." % key)
    return value


def require_int(body, key):
    if key not in body:
        raise errors.validation("Missing required field: %s" % key)
    value = body[key]
    # bool is a subclass of int — reject it explicitly.
    if isinstance(value, bool) or not isinstance(value, int):
        raise errors.validation("Field %s must be an integer." % key)
    return value


def optional_int(body, key, default=None):
    if key not in body or body[key] is None:
        return default
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise errors.validation("Field %s must be an integer." % key)
    return value


def require_number(body, key):
    if key not in body:
        raise errors.validation("Missing required field: %s" % key)
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise errors.validation("Field %s must be a number." % key)
    return value


def optional_number(body, key, default=None):
    if key not in body or body[key] is None:
        return default
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise errors.validation("Field %s must be a number." % key)
    return value


def optional_string(body, key, default=None):
    if key not in body or body[key] is None:
        return default
    value = body[key]
    if not isinstance(value, str):
        raise errors.validation("Field %s must be a string." % key)
    return value


def parse_pagination():
    """Parse limit/offset query params per PRD §2.3.

    limit: default 10, min 1, max 100.
    offset: default 0, min 0.
    Out-of-range or non-integer values are ERR_VALIDATION.
    """
    from flask import request

    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise errors.validation("limit must be an integer.")
        if limit < 1 or limit > 100:
            raise errors.validation("limit must be between 1 and 100.")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise errors.validation("offset must be an integer.")
        if offset < 0:
            raise errors.validation("offset must be >= 0.")

    return limit, offset


def paginate(items, limit, offset):
    """items is the fully-sorted list. Returns the page slice."""
    return items[offset:offset + limit]
