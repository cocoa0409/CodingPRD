"""Shared body / pagination validation helpers."""
from flask import request
from errors import err


def get_json_body():
    """Return the parsed JSON body as a dict (empty dict if none/invalid-empty)."""
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def parse_pagination():
    """Return (limit, offset) from query params, validated (PRD §2.3).
    Raises ERR_VALIDATION_PAGINATION on out-of-bounds."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            raise err("ERR_VALIDATION_PAGINATION", "limit must be an integer")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise err("ERR_VALIDATION_PAGINATION", "offset must be an integer")

    if limit < 1 or limit > 100:
        raise err("ERR_VALIDATION_PAGINATION", "limit must be between 1 and 100")
    if offset < 0:
        raise err("ERR_VALIDATION_PAGINATION", "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """Slice an already-sorted list."""
    return items[offset:offset + limit]


def require_fields(body, fields):
    for f in fields:
        if body.get(f) is None:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % f)


def require_enum(value, allowed, field):
    if value not in allowed:
        raise err("ERR_INVALID_REQUEST", "Invalid value for %s" % field)


def require_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", "Field %s must be a non-empty string" % field)
    return v
