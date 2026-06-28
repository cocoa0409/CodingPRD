"""Shared request helpers: body parsing, pagination, validation primitives."""
from flask import request

from errors import err


def get_body():
    if request.method in ("POST", "PATCH", "PUT"):
        if request.data and len(request.data) > 0:
            data = request.get_json(silent=True)
            if data is None:
                raise err("ERR_INVALID_REQUEST", "Malformed JSON body")
            if not isinstance(data, dict):
                raise err("ERR_INVALID_REQUEST", "Body must be a JSON object")
            return data
        return {}
    return {}


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {f}")


def require_string(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a non-empty string")
    return v


def require_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an integer")
    return v


def require_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be one of {sorted(allowed)}")
    return v


def optional_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a boolean")
    return v


def parse_pagination():
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_VALUE_OUT_OF_RANGE", "limit must be between 1 and 100")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise err("ERR_VALUE_OUT_OF_RANGE", "offset must be >= 0")
    return limit, offset


def paginate(rows, limit, offset):
    """rows already sorted. Returns (page, pagination_meta)."""
    total = len(rows)
    page = rows[offset:offset + limit]
    has_more = (offset + limit) < total
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
    return page, meta


def sort_by_created(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["id"]))
