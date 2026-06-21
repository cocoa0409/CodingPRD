"""Request body parsing, pagination, and field validation helpers.

Validation ordering follows PRD §2.9. These helpers raise ApiError with the
correct error_id; the caller invokes them in the prescribed order.
"""
from flask import request

from errors import err


def get_json_body():
    """Return the parsed JSON body as a dict (empty dict if no body)."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "Malformed JSON body")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Body must be a JSON object")
    return data


def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def require_present(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", f"Missing required field: {field}")
    return body[field]


def require_number(body, field):
    v = require_present(body, field)
    if not is_number(v):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a number")
    return v


def require_int(body, field):
    v = require_present(body, field)
    if not is_int(v):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an integer")
    return v


def require_string(body, field):
    v = require_present(body, field)
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a string")
    return v


def parse_pagination():
    """Parse and validate limit/offset (PRD §2.3). Returns (limit, offset)."""
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_PAGINATION_INVALID", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_PAGINATION_INVALID", "limit out of bounds")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_PAGINATION_INVALID", "offset must be an integer")
        if offset < 0:
            raise err("ERR_PAGINATION_INVALID", "offset out of bounds")
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at asc (PRD §2.3) and slice."""
    ordered = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    has_more = offset + limit < total
    return page, total, has_more
