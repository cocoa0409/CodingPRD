"""Shared helpers: record construction, pagination, input validation."""

from flask import request

from db import new_id, now_iso
from errors import raise_err, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from response import success


def base_record(common=True):
    rec = {"id": new_id(), "created_at": now_iso()}
    if common:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(rec):
    """Refresh updated_at and bump version on a mutable record."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1


def get_or_404(store, rid, what="resource"):
    rec = store.get(rid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "%s does not exist" % what)
    return rec


def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def req_str(data, field):
    v = data.get(field)
    if v is None or not isinstance(v, str) or v == "":
        raise_err(ERR_INVALID_REQUEST, "Required input missing or wrong type: %s" % field)
    return v


def opt_str(data, field, default=None):
    v = data.get(field, default)
    if v is not None and not isinstance(v, str):
        raise_err(ERR_INVALID_REQUEST, "Required input missing or wrong type: %s" % field)
    return v


def req_int(data, field):
    v = data.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        raise_err(ERR_INVALID_REQUEST, "Required input missing or wrong type: %s" % field)
    return v


def opt_int(data, field, default=None):
    v = data.get(field, default)
    if v is not None and (isinstance(v, bool) or not isinstance(v, int)):
        raise_err(ERR_INVALID_REQUEST, "Required input missing or wrong type: %s" % field)
    return v


def opt_bool(data, field, default=None):
    v = data.get(field, default)
    if v is not None and not isinstance(v, bool):
        raise_err(ERR_INVALID_REQUEST, "Required input missing or wrong type: %s" % field)
    return v


def req_enum(data, field, allowed):
    v = req_str(data, field)
    if v not in allowed:
        raise_err(ERR_INVALID_REQUEST, "Required input missing or wrong type: %s" % field)
    return v


def opt_enum(data, field, allowed, default=None):
    v = data.get(field, default)
    if v is not None and v not in allowed:
        raise_err(ERR_INVALID_REQUEST, "Required input missing or wrong type: %s" % field)
    return v


def paginate(items, status=200):
    """Offset/limit pagination using scaffold pagination_fields/defaults."""
    args = request.args
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise_err(ERR_INVALID_REQUEST, "limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise_err(ERR_INVALID_REQUEST, "offset must be an integer")
    if limit < 1 or limit > 100 or offset < 0:
        raise_err(ERR_INVALID_REQUEST, "limit/offset out of bounds")

    # Sort by created_at ascending (PRD §2.3), stable by id
    items = sorted(items, key=lambda r: (r.get("created_at", ""), r.get("id", "")))
    total = len(items)
    page = items[offset:offset + limit]
    return success(
        page,
        status=status,
        pagination={
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": (offset + limit) < total,
        },
    )
