"""Shared helpers: common fields, pagination, body parsing, FK resolution.

Common system fields (PRD §2.4):
    id          — server-minted UUID, no prefix
    created_at  — ISO 8601 UTC, three fractional digits, set at create
    updated_at  — ISO 8601 UTC, three fractional digits, refreshed on mutation
    version     — integer starting at 1, +1 on every mutation
"""

from flask import request

from db import new_id, store
from errors import (
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_REFERENCED_RESOURCE_NOT_FOUND,
    ERR_VALIDATION_PAGINATION,
    err,
)
from response import now_iso


def init_common(record):
    """Stamp id + common system fields on a freshly created record."""
    ts = now_iso()
    record["id"] = new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = store.next_seq()
    return record


def touch(record):
    """Refresh updated_at and bump version on a mutation."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1
    return record


def get_json_body():
    """Parse the JSON body; tolerate empty bodies (return {})."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def require_fields(body, fields):
    """Ensure required fields are present (not None). priority 5 / ERR_INVALID_REQUEST."""
    for f in fields:
        if body.get(f) is None:
            raise err(ERR_INVALID_REQUEST, f"Missing required field: {f}")


def parse_pagination():
    """Parse limit/offset. ERR_VALIDATION_PAGINATION (422) when out of bounds.

    Defaults: limit=10 (min 1, max 100), offset=0 (min 0).
    """
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err(ERR_VALIDATION_PAGINATION, "limit must be an integer")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err(ERR_VALIDATION_PAGINATION, "offset must be an integer")

    if limit < 1 or limit > 100:
        raise err(ERR_VALIDATION_PAGINATION, "limit must be in [1, 100]")
    if offset < 0:
        raise err(ERR_VALIDATION_PAGINATION, "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ASC (tie-break by creation sequence), then slice.

    Returns (page_items, list_meta).
    """
    ordered = sorted(items, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    list_meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, list_meta


def get_or_404(collection, resource_id):
    """Look up a path-referenced resource or raise ERR_NOT_FOUND (priority 3)."""
    rec = collection.get(resource_id)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Resource not found")
    return rec


def resolve_fk(collection, fk_id):
    """Resolve a body FK target or raise ERR_REFERENCED_RESOURCE_NOT_FOUND (priority 4)."""
    rec = collection.get(fk_id)
    if rec is None:
        raise err(ERR_REFERENCED_RESOURCE_NOT_FOUND, "Referenced resource not found")
    return rec
