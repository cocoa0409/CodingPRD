"""Request-body validation helpers (priority 4: ERR_INVALID_REQUEST)."""
from flask import request

import errors


def get_json_body():
    """Return the parsed JSON body as a dict, or {} when absent/empty.

    Malformed JSON -> ERR_INVALID_REQUEST.
    """
    if request.content_length in (None, 0) and not (request.data or b"").strip():
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        errors.raise_err(errors.ERR_INVALID_REQUEST, "Malformed JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        errors.raise_err(errors.ERR_INVALID_REQUEST, "Body must be a JSON object")
    return body


def require(body, field):
    if field not in body or body[field] is None:
        errors.raise_err(errors.ERR_INVALID_REQUEST, f"Missing required field: {field}")
    return body[field]


def opt(body, field, default):
    if field not in body or body[field] is None:
        return default
    return body[field]


def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def as_positive_number(v, field):
    if not is_number(v) or v <= 0:
        errors.raise_err(errors.ERR_INVALID_REQUEST, f"{field} must be a positive number")
    return v


def as_nonneg_number(v, field):
    if not is_number(v) or v < 0:
        errors.raise_err(errors.ERR_INVALID_REQUEST, f"{field} must be a non-negative number")
    return v


def as_positive_int(v, field):
    if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
        errors.raise_err(errors.ERR_INVALID_REQUEST, f"{field} must be a positive integer")
    return v


def as_nonneg_int(v, field):
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
        errors.raise_err(errors.ERR_INVALID_REQUEST, f"{field} must be a non-negative integer")
    return v


def as_bool(v, field):
    if not isinstance(v, bool):
        errors.raise_err(errors.ERR_INVALID_REQUEST, f"{field} must be a boolean")
    return v


def as_enum(v, field, allowed):
    if v not in allowed:
        errors.raise_err(errors.ERR_INVALID_REQUEST, f"{field} must be one of {sorted(allowed)}")
    return v


def as_string(v, field):
    if not isinstance(v, str) or v.strip() == "":
        errors.raise_err(errors.ERR_INVALID_REQUEST, f"{field} must be a non-empty string")
    return v


PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0
PAGINATION_MIN_OFFSET = 0


def parse_pagination():
    """limit default 10 (min 1, max 100); offset default 0 (min 0)."""
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")

    if limit_raw is None:
        limit = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            errors.raise_err(errors.ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < PAGINATION_MIN_LIMIT:
            limit = PAGINATION_MIN_LIMIT
        elif limit > PAGINATION_MAX_LIMIT:
            limit = PAGINATION_MAX_LIMIT

    if offset_raw is None:
        offset = PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            errors.raise_err(errors.ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < PAGINATION_MIN_OFFSET:
            offset = PAGINATION_MIN_OFFSET

    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset : offset + limit]
    return page, total
