"""Shared helpers: mutation bookkeeping, pagination, body parsing."""
from flask import request

import db
from db import new_id, now_ts
from errors import err


def touch(entity):
    """Refresh updated_at and bump version on a mutation."""
    entity["updated_at"] = now_ts()
    entity["version"] += 1


def new_common(**fields):
    """Build an entity with id, created_at, updated_at, version=1."""
    ts = now_ts()
    base = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    base.update(fields)
    return base


def get_json_body():
    """Return the JSON body as a dict; raise ERR_INVALID_REQUEST if malformed."""
    if request.method in ("POST", "PUT", "PATCH"):
        if request.content_length in (None, 0) and not request.data:
            return {}
        try:
            body = request.get_json(force=True, silent=True)
        except Exception:
            raise err("ERR_INVALID_REQUEST", "Malformed JSON body")
        if body is None:
            # No body / unparseable. Treat empty as {}.
            if request.data and request.data.strip():
                raise err("ERR_INVALID_REQUEST", "Malformed JSON body")
            return {}
        if not isinstance(body, dict):
            raise err("ERR_INVALID_REQUEST", "Request body must be an object")
        return body
    return {}


def parse_pagination():
    """Parse limit/offset query params per PRD 2.3."""
    args = request.args
    limit = args.get("limit")
    offset = args.get("offset")
    if limit is None:
        limit_val = 10
    else:
        try:
            limit_val = int(limit)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit_val < 1:
            raise err("ERR_INVALID_REQUEST", "limit may not be smaller than 1")
        if limit_val > 100:
            raise err("ERR_INVALID_REQUEST", "limit may not exceed 100")
    if offset is None:
        offset_val = 0
    else:
        try:
            offset_val = int(offset)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset_val < 0:
            raise err("ERR_INVALID_REQUEST", "offset may not be negative")
    return limit_val, offset_val


def paginate(items, serializer):
    """Sort by created_at asc, apply limit/offset, return (data, meta)."""
    limit, offset = parse_pagination()
    ordered = sorted(items, key=lambda x: (x["created_at"], x["id"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    data = [serializer(x) for x in page]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return data, pagination


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {f}")


def require_int(body, field, minimum=None):
    val = body.get(field)
    if not isinstance(val, int) or isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", f"{field} must be an integer")
    if minimum is not None and val < minimum:
        raise err("ERR_INVALID_REQUEST", f"{field} must be >= {minimum}")
    return val


def require_str(body, field):
    val = body.get(field)
    if not isinstance(val, str) or val.strip() == "":
        raise err("ERR_INVALID_REQUEST", f"{field} must be a non-empty string")
    return val


def opt_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", f"{field} must be a boolean")
    return val
