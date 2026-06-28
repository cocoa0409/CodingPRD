"""Body-field and pagination validation helpers.

These implement priority-4 request well-formedness (ERR_INVALID_REQUEST) and the
pagination bounds check (ERR_PAGINATION_INVALID) from PRD sections 2.3 / 2.10.
"""

from flask import request

import errors

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def get_json_body():
    """Return the JSON body as a dict (empty dict when absent)."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def require_string(body, field):
    val = body.get(field)
    if val is None or not isinstance(val, str) or val == "":
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field '{field}' is required and must be a non-empty string")
    return val


def optional_string(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field '{field}' must be a string")
    return val


def require_int(body, field, minimum=None):
    val = body.get(field)
    if val is None or isinstance(val, bool) or not isinstance(val, int):
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field '{field}' is required and must be an integer")
    if minimum is not None and val < minimum:
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field '{field}' must be >= {minimum}")
    return val


def optional_int(body, field, default=None, minimum=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field '{field}' must be an integer")
    if minimum is not None and val < minimum:
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field '{field}' must be >= {minimum}")
    return val


def require_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field '{field}' must be a boolean")
    return val


def require_enum(body, field, allowed):
    val = require_string(body, field)
    if val not in allowed:
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field '{field}' must be one of {sorted(allowed)}")
    return val


def optional_enum(body, field, allowed, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str) or val not in allowed:
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field '{field}' must be one of {sorted(allowed)}")
    return val


def parse_pagination():
    """Parse and validate limit/offset query params. Returns (limit, offset)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise errors.err(errors.ERR_PAGINATION_INVALID, "limit must be an integer")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise errors.err(errors.ERR_PAGINATION_INVALID, "limit must be between 1 and 100")

    if offset_raw is None:
        offset = PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise errors.err(errors.ERR_PAGINATION_INVALID, "offset must be an integer")
        if offset < 0:
            raise errors.err(errors.ERR_PAGINATION_INVALID, "offset must be >= 0")

    return limit, offset


def paginate(items, limit, offset):
    """Slice an already-sorted list of items by limit/offset."""
    return items[offset:offset + limit]
