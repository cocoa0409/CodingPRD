from flask import request
from errors import (err, ERR_VALIDATION, ERR_INVALID_FIELD_VALUE)


def get_json_body():
    """Parse JSON body; tolerate empty body for endpoints with no input."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise err(ERR_VALIDATION, "Malformed JSON body.")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err(ERR_VALIDATION, "Request body must be a JSON object.")
    return data


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err(ERR_VALIDATION, f"Missing required field: {f}")


def parse_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err(ERR_VALIDATION, "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise err(ERR_VALIDATION, "limit out of bounds (1..100).")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err(ERR_VALIDATION, "offset must be an integer.")
        if offset < 0:
            raise err(ERR_VALIDATION, "offset out of bounds (>=0).")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    window = items[offset:offset + limit]
    return window, total


def sort_by_created(items):
    return sorted(items, key=lambda x: (x["created_at"], x["_seq"]))


def require_int(body, field, minimum=None):
    v = body.get(field)
    if not isinstance(v, int) or isinstance(v, bool):
        raise err(ERR_INVALID_FIELD_VALUE, f"{field} must be an integer.")
    if minimum is not None and v < minimum:
        raise err(ERR_INVALID_FIELD_VALUE, f"{field} must be >= {minimum}.")
    return v
