"""Body / pagination validation helpers."""
from flask import request
from errors import err


def get_json_body():
    if request.method in ("POST", "PUT", "PATCH"):
        body = request.get_json(silent=True)
        if body is None:
            return {}
        if not isinstance(body, dict):
            return {}
        return body
    return {}


def parse_pagination():
    """Returns (limit, offset). Raises ERR_INVALID_PAGINATION if out of bounds."""
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_PAGINATION", "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_PAGINATION", "limit out of range 1-100.")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_PAGINATION", "offset must be an integer.")
        if offset < 0:
            raise err("ERR_INVALID_PAGINATION", "offset must be >= 0.")

    return limit, offset


def paginate(items, limit, offset):
    """items already sorted. Returns (page_items, pagination_meta)."""
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + limit) < total
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
    return page, meta


def sort_by_created(items):
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_MISSING_REQUIRED_FIELD", f"Missing required field: {f}")


def require_enum(value, allowed, field):
    if value not in allowed:
        raise err("ERR_INVALID_FIELD_VALUE", f"Invalid value for {field}.")
