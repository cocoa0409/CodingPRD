"""Common helpers for entity management — common fields, pagination."""
from flask import request

from clock import get_now, format_iso
from db import new_id
from errors import api_error


def stamp_new(entity: dict) -> dict:
    """Stamp a new entity with id, created_at, updated_at, version."""
    now = format_iso(get_now())
    entity["id"] = new_id()
    entity["created_at"] = now
    entity["updated_at"] = now
    entity["version"] = 1
    return entity


def stamp_update(entity: dict):
    entity["updated_at"] = format_iso(get_now())
    entity["version"] = entity.get("version", 1) + 1


def check_version(entity: dict, body: dict):
    if body is None:
        return
    ver = body.get("version")
    if ver is None:
        return
    try:
        ver = int(ver)
    except (TypeError, ValueError):
        raise api_error("ERR_VERSION_CONFLICT", "version mismatch")
    if ver != entity.get("version"):
        raise api_error("ERR_VERSION_CONFLICT", "version mismatch")


def paginate(items: list, sort_key=None):
    """Parses limit/offset from query string, sorts, returns (page, pagination_meta)."""
    args = request.args
    limit_raw = args.get("limit", "10")
    offset_raw = args.get("offset", "0")
    try:
        limit = int(limit_raw)
        offset = int(offset_raw)
    except (TypeError, ValueError):
        raise api_error("ERR_PAGINATION_OUT_OF_RANGE", "invalid limit/offset")
    if limit < 1 or limit > 100 or offset < 0:
        raise api_error("ERR_PAGINATION_OUT_OF_RANGE", "limit out of range or offset negative")
    if sort_key is None:
        sort_key = lambda x: x.get("created_at", "")
    items = sorted(items, key=sort_key)
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


def get_json_body():
    """Return request JSON body as dict, or empty dict if no body."""
    try:
        body = request.get_json(silent=True) or {}
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    return body
