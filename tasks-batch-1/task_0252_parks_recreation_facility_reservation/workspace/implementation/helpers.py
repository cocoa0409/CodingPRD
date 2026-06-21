"""Shared parsing/validation/pagination helpers."""
from datetime import datetime, timezone

import errors


def parse_body():
    from flask import request
    if request.method in ("POST", "PATCH", "PUT"):
        if request.content_length in (None, 0) and not request.data:
            return {}
        try:
            body = request.get_json(force=True, silent=True)
        except Exception:
            body = None
        if body is None:
            return {}
        if not isinstance(body, dict):
            raise errors.err(errors.ERR_VALIDATION, "Request body must be a JSON object")
        return body
    return {}


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise errors.err(errors.ERR_VALIDATION, f"Missing required field: {f}")


def parse_dt(value, field="datetime"):
    """Parse an ISO 8601 datetime string into an aware UTC datetime."""
    if not isinstance(value, str):
        raise errors.err(errors.ERR_VALIDATION, f"Invalid {field}: must be ISO 8601 string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise errors.err(errors.ERR_VALIDATION, f"Invalid {field}: not ISO 8601")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def require_int(body, field, minimum=None, maximum=None):
    v = body.get(field)
    if not isinstance(v, int) or isinstance(v, bool):
        raise errors.err(errors.ERR_VALIDATION, f"{field} must be an integer")
    if minimum is not None and v < minimum:
        raise errors.err(errors.ERR_VALIDATION, f"{field} below minimum")
    if maximum is not None and v > maximum:
        raise errors.err(errors.ERR_VALIDATION, f"{field} above maximum")
    return v


def require_number(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise errors.err(errors.ERR_VALIDATION, f"{field} must be a number")
    return v


def require_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        raise errors.err(errors.ERR_VALIDATION, f"{field} must be one of {sorted(allowed)}")
    return v


def paginate(items, args):
    """Apply limit/offset pagination (PRD §2.3). Returns (page, meta)."""
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")

    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise errors.err(errors.ERR_PAGINATION_INVALID, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise errors.err(errors.ERR_PAGINATION_INVALID, "limit out of bounds [1,100]")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise errors.err(errors.ERR_PAGINATION_INVALID, "offset must be an integer")
        if offset < 0:
            raise errors.err(errors.ERR_PAGINATION_INVALID, "offset out of bounds [0,)")

    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta


def sort_by_created(items):
    """Sort by created_at ascending (PRD §2.3 default)."""
    return sorted(items, key=lambda r: (r["created_at"], r["id"]))
