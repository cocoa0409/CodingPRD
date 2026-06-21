"""Request-shape validation helpers. PRD §2.6 (ERR_INVALID_REQUEST) and §2.3 pagination."""
from flask import request

from errors import err


def require_fields(body, fields):
    """Each field must be present and non-null. ERR_INVALID_REQUEST otherwise."""
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {f}")


def require_string(body, field, required=True, allow_empty=False):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {field}")
        return None
    val = body[field]
    if not isinstance(val, str):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a string")
    if not allow_empty and val == "":
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be non-empty")
    return val


def require_int(body, field, required=True, minimum=None):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {field}")
        return None
    val = body[field]
    # bool is a subclass of int — reject it explicitly.
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an integer")
    if minimum is not None and val < minimum:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be >= {minimum}")
    return val


def require_bool(body, field, default=None, required=False):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {field}")
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a boolean")
    return val


def require_enum(body, field, members, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {field}")
        return default
    val = body[field]
    if val not in members:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be one of {sorted(members)}")
    return val


def parse_pagination():
    """Parse limit/offset query params. PRD §2.3.

    limit default 10, min 1, max 100; offset default 0, min 0.
    Out-of-bounds -> ERR_VALIDATION_PAGINATION (422).
    """
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            raise err("ERR_VALIDATION_PAGINATION", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_VALIDATION_PAGINATION", "limit out of bounds")

    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise err("ERR_VALIDATION_PAGINATION", "offset must be an integer")
        if offset < 0:
            raise err("ERR_VALIDATION_PAGINATION", "offset out of bounds")

    return limit, offset


def paginate(items, limit, offset):
    """Slice a list according to limit/offset; return (page, total_count)."""
    total = len(items)
    page = items[offset:offset + limit]
    return page, total
