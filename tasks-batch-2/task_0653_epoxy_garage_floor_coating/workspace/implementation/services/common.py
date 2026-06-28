"""Shared helpers: entity construction, mutation (version/updated_at bump),
pagination, and request-body field validation."""
from flask import request

from db import db, new_id
from errors import err


# ---------------------------------------------------------------------------
# Entity construction & mutation
# ---------------------------------------------------------------------------
def new_row(extra):
    """Build a row carrying the common fields (PRD §2.4): id, created_at,
    updated_at, version=1, plus a monotonic creation sequence."""
    now = db.now()
    row = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }
    row.update(extra)
    return row


def touch(row):
    """Refresh updated_at and increment version by exactly 1 (PRD §2.4)."""
    row["updated_at"] = db.now()
    row["version"] += 1


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def parse_pagination():
    args = request.args
    limit = args.get("limit")
    offset = args.get("offset")

    if limit is None:
        limit = 10
    else:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_VALIDATION", "limit must be between 1 and 100")

    if offset is None:
        offset = 0
    else:
        try:
            offset = int(offset)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION", "offset must be an integer")
        if offset < 0:
            raise err("ERR_VALIDATION", "offset must be >= 0")

    return limit, offset


def paginate(rows, limit, offset):
    """Sort by created_at ascending (creation order via _seq), slice, and build
    pagination meta (PRD §2.3)."""
    ordered = sorted(rows, key=lambda r: r["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta


# ---------------------------------------------------------------------------
# Body / field validation (priority 21 — ERR_VALIDATION)
# ---------------------------------------------------------------------------
def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_VALIDATION", "Request body must be a JSON object")
    return data


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_VALIDATION", f"Missing required field: {f}")


def require_int(body, field, minimum=None, maximum=None):
    v = body.get(field)
    if v is None:
        raise err("ERR_VALIDATION", f"Missing required field: {field}")
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_VALIDATION", f"{field} must be an integer")
    if minimum is not None and v < minimum:
        raise err("ERR_VALIDATION", f"{field} must be >= {minimum}")
    if maximum is not None and v > maximum:
        raise err("ERR_VALIDATION", f"{field} must be <= {maximum}")
    return v


def require_str(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v == "":
        raise err("ERR_VALIDATION", f"{field} must be a non-empty string")
    return v


def require_bool(body, field, default=None):
    if field not in body or body[field] is None:
        if default is None:
            raise err("ERR_VALIDATION", f"Missing required field: {field}")
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise err("ERR_VALIDATION", f"{field} must be a boolean")
    return v


def require_enum(body, field, allowed):
    v = body.get(field)
    if v is None:
        raise err("ERR_VALIDATION", f"Missing required field: {field}")
    if v not in allowed:
        raise err("ERR_VALIDATION", f"{field} must be one of {sorted(allowed)}")
    return v
