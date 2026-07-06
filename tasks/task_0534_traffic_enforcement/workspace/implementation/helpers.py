from datetime import datetime, timezone

from flask import request

from clock import format_iso_ms
from db import db
from errors import err, ERR_INVALID_REQUEST, ERR_NOT_FOUND


def touch_common(record):
    """Refresh updated_at and bump version on a mutation."""
    record["updated_at"] = format_iso_ms(datetime.now(timezone.utc))
    record["version"] = record.get("version", 1) + 1


def base_common():
    """Create the common server-managed fields for a full (versioned) resource."""
    ts = format_iso_ms(datetime.now(timezone.utc))
    return {
        "id": db.new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def base_audit():
    """Common fields for an append-only audit record (id + created_at only)."""
    ts = format_iso_ms(datetime.now(timezone.utc))
    return {
        "id": db.new_id(),
        "created_at": ts,
        "_seq": db.next_seq(),
    }


def public(record):
    """Strip internal fields (leading underscore) for serialization."""
    return {k: v for k, v in record.items() if not k.startswith("_")}


def get_json_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err(ERR_INVALID_REQUEST, f"Missing required field: {f}")


def require_int(body, field, positive=False, non_negative=False):
    v = body.get(field)
    if not isinstance(v, int) or isinstance(v, bool):
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be an integer")
    if positive and v <= 0:
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be positive")
    if non_negative and v < 0:
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be non-negative")
    return v


def require_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be a non-empty string")
    return v


def require_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be one of {sorted(allowed)}")
    return v


def parse_pagination():
    """Read limit/offset query params per PRD (limit default 10, min 1, max 100; offset default 0)."""
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    if limit is None:
        limit_v = 10
    else:
        try:
            limit_v = int(limit)
        except (ValueError, TypeError):
            raise err(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit_v < 1:
            limit_v = 1
        if limit_v > 100:
            limit_v = 100
    if offset is None:
        offset_v = 0
    else:
        try:
            offset_v = int(offset)
        except (ValueError, TypeError):
            raise err(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset_v < 0:
            offset_v = 0
    return limit_v, offset_v


def paginate(items):
    """Sort by created_at ascending (via _seq), slice, and return (page, meta)."""
    limit_v, offset_v = parse_pagination()
    ordered = sorted(items, key=lambda r: r.get("_seq", 0))
    total = len(ordered)
    page = ordered[offset_v:offset_v + limit_v]
    meta = {
        "limit": limit_v,
        "offset": offset_v,
        "total_count": total,
        "has_more": offset_v + limit_v < total,
    }
    return [public(r) for r in page], meta


def find_or_404(collection, rid):
    rec = collection.get(rid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Resource not found")
    return rec
