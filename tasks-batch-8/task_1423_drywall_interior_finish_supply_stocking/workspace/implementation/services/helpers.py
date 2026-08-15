"""Shared helpers: pagination, body validation, common fields."""
from flask import request
from errors import ApiError, ERR_VALIDATION
from db import now_iso, new_id


def parse_pagination():
    """Parse limit/offset from query string with defaults and bounds."""
    try:
        limit = int(request.args.get("limit", "10"))
    except (TypeError, ValueError):
        raise ApiError(ERR_VALIDATION, "limit must be an integer", 400)
    try:
        offset = int(request.args.get("offset", "0"))
    except (TypeError, ValueError):
        raise ApiError(ERR_VALIDATION, "offset must be an integer", 400)
    if limit < 1 or limit > 100:
        raise ApiError(ERR_VALIDATION, "limit must be between 1 and 100", 400)
    if offset < 0:
        raise ApiError(ERR_VALIDATION, "offset must be >= 0", 400)
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset : offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }


def body():
    """Return parsed JSON body (may be empty dict)."""
    if request.data:
        try:
            return request.get_json(force=True, silent=False) or {}
        except Exception:
            raise ApiError(ERR_VALIDATION, "Request body must be valid JSON", 400)
    return {}


def require_fields(b, *fields):
    missing = [f for f in fields if f not in b]
    if missing:
        raise ApiError(ERR_VALIDATION, f"Missing required fields: {', '.join(missing)}", 400)


def require_int(b, field, min_val=None, max_val=None):
    v = b.get(field)
    if not isinstance(v, int) or isinstance(v, bool):
        raise ApiError(ERR_VALIDATION, f"{field} must be an integer", 400)
    if min_val is not None and v < min_val:
        raise ApiError(ERR_VALIDATION, f"{field} must be >= {min_val}", 400)
    if max_val is not None and v > max_val:
        raise ApiError(ERR_VALIDATION, f"{field} must be <= {max_val}", 400)
    return v


def require_str(b, field):
    v = b.get(field)
    if not isinstance(v, str) or not v:
        raise ApiError(ERR_VALIDATION, f"{field} must be a non-empty string", 400)
    return v


def require_enum(b, field, allowed):
    v = b.get(field)
    if v not in allowed:
        raise ApiError(ERR_VALIDATION, f"{field} must be one of {sorted(allowed)}", 400)
    return v


def new_common_fields():
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }


def touch(entity):
    entity["updated_at"] = now_iso()
    entity["version"] += 1
