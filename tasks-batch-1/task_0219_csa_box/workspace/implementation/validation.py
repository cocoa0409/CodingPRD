"""Request-body and query-parameter validation helpers.

Pagination defaults (PRD §2.3 / SCAFFOLD §1.0):
  limit  default 10, min 1, max 100
  offset default 0, no upper bound, must be >= 0
Out-of-bounds -> ERR_VALIDATION_PAGINATION (422).
"""
from flask import request

from errors import (err, ERR_INVALID_REQUEST, ERR_VALIDATION_PAGINATION)


def get_json_body():
    """Return the parsed JSON body as a dict, or {} when absent.

    A body that is present but not a JSON object raises ERR_INVALID_REQUEST."""
    if request.method in ("POST", "DELETE", "PUT", "PATCH"):
        data = request.get_json(silent=True)
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object.")
        return data
    return {}


def parse_pagination():
    """Parse and validate limit/offset query params. Returns (limit, offset)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    limit = 10
    offset = 0

    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            raise err(ERR_VALIDATION_PAGINATION, "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise err(ERR_VALIDATION_PAGINATION, "limit must be between 1 and 100.")

    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise err(ERR_VALIDATION_PAGINATION, "offset must be an integer.")
        if offset < 0:
            raise err(ERR_VALIDATION_PAGINATION, "offset must be >= 0.")

    return limit, offset


def paginate(items, limit, offset):
    """Slice an already-sorted list; return (page, pagination_meta)."""
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta


def require_fields(body, fields):
    """Ensure each named field is present (not None). Raises ERR_INVALID_REQUEST."""
    for f in fields:
        if body.get(f) is None:
            raise err(ERR_INVALID_REQUEST, "Missing required field: %s" % f)


def require_int(body, field, *, minimum=None, maximum=None, allow_zero=True,
                positive=False, required=True, default=None):
    """Validate an integer field with optional bounds."""
    if field not in body or body.get(field) is None:
        if required:
            raise err(ERR_INVALID_REQUEST, "Missing required field: %s" % field)
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(ERR_INVALID_REQUEST, "%s must be an integer." % field)
    if positive and val <= 0:
        raise err(ERR_INVALID_REQUEST, "%s must be a positive integer." % field)
    if not allow_zero and val == 0:
        raise err(ERR_INVALID_REQUEST, "%s must not be zero." % field)
    if minimum is not None and val < minimum:
        raise err(ERR_INVALID_REQUEST, "%s must be >= %s." % (field, minimum))
    if maximum is not None and val > maximum:
        raise err(ERR_INVALID_REQUEST, "%s must be <= %s." % (field, maximum))
    return val


def require_number(body, field, *, positive=False, required=True, default=None):
    """Validate a numeric (int or float) field."""
    if field not in body or body.get(field) is None:
        if required:
            raise err(ERR_INVALID_REQUEST, "Missing required field: %s" % field)
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err(ERR_INVALID_REQUEST, "%s must be a number." % field)
    if positive and val <= 0:
        raise err(ERR_INVALID_REQUEST, "%s must be greater than zero." % field)
    return val


def require_enum(body, field, allowed, *, required=True, default=None):
    """Validate an enum field against an allowed set."""
    if field not in body or body.get(field) is None:
        if required:
            raise err(ERR_INVALID_REQUEST, "Missing required field: %s" % field)
        return default
    val = body[field]
    if val not in allowed:
        raise err(ERR_INVALID_REQUEST,
                  "%s must be one of %s." % (field, sorted(allowed)))
    return val


def require_string(body, field, *, required=True, default=None, allow_empty=True):
    if field not in body or body.get(field) is None:
        if required:
            raise err(ERR_INVALID_REQUEST, "Missing required field: %s" % field)
        return default
    val = body[field]
    if not isinstance(val, str):
        raise err(ERR_INVALID_REQUEST, "%s must be a string." % field)
    if not allow_empty and val.strip() == "":
        raise err(ERR_INVALID_REQUEST, "%s must not be empty." % field)
    return val


def require_bool(body, field, *, required=False, default=False):
    if field not in body or body.get(field) is None:
        if required:
            raise err(ERR_INVALID_REQUEST, "Missing required field: %s" % field)
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise err(ERR_INVALID_REQUEST, "%s must be a boolean." % field)
    return val
