"""Shared helpers: body parsing, pagination, type validation."""
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import errors

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def get_json_body():
    """Parse the JSON body. Returns {} when absent. Raises ERR_INVALID_REQUEST
    when the body is present but not a JSON object."""
    if request.content_length in (None, 0) and not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "Malformed JSON body")
    if data is None:
        return {}
    if not isinstance(data, dict):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "Body must be a JSON object")
    return data


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            errors.raise_error(errors.ERR_INVALID_REQUEST, f"Missing required field: {f}")


def require_string(body, field, required=True):
    if field not in body or body[field] is None:
        if required:
            errors.raise_error(errors.ERR_INVALID_REQUEST, f"Missing required field: {field}")
        return None
    val = body[field]
    if not isinstance(val, str) or val == "":
        errors.raise_error(errors.ERR_INVALID_REQUEST, f"Field {field} must be a non-empty string")
    return val


def require_int(body, field, required=True):
    if field not in body or body[field] is None:
        if required:
            errors.raise_error(errors.ERR_INVALID_REQUEST, f"Missing required field: {field}")
        return None
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        errors.raise_error(errors.ERR_INVALID_REQUEST, f"Field {field} must be an integer")
    return val


def require_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        errors.raise_error(errors.ERR_INVALID_REQUEST, f"Field {field} must be a boolean")
    return val


def require_enum(body, field, allowed, required=True):
    if field not in body or body[field] is None:
        if required:
            errors.raise_error(errors.ERR_INVALID_REQUEST, f"Missing required field: {field}")
        return None
    val = body[field]
    if val not in allowed:
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           f"Field {field} must be one of {sorted(allowed)}")
    return val


def get_pagination():
    """Parse limit/offset query params. Raises ERR_INVALID_REQUEST on bad values."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            errors.raise_error(errors.ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            errors.raise_error(errors.ERR_INVALID_REQUEST,
                               f"limit must be between {PAGINATION_MIN_LIMIT} and {PAGINATION_MAX_LIMIT}")

    if offset_raw is None:
        offset = PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            errors.raise_error(errors.ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            errors.raise_error(errors.ERR_INVALID_REQUEST, "offset must be >= 0")

    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ascending, then apply offset/limit."""
    ordered = sorted(items, key=lambda o: (o.get("created_at", ""), o.get("id", "")))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return window, total


def round_half_up(value):
    """Round a Decimal/number half-up to the nearest integer."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
