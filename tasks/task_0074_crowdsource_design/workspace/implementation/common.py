"""Common helpers: stamping, OCC, body parsing, pagination."""
from flask import request

from clock import format_iso, get_now
from db import new_id
from errors import api_error


# --- Identity stamping --------------------------------------------------------


def stamp_new(entity: dict, with_common: bool = True) -> dict:
    now = format_iso(get_now())
    entity["id"] = new_id()
    entity["created_at"] = now
    if with_common:
        entity["updated_at"] = now
        entity["version"] = 1
    return entity


def stamp_update(entity: dict):
    if "updated_at" in entity or "version" in entity:
        entity["updated_at"] = format_iso(get_now())
        entity["version"] = int(entity.get("version", 1)) + 1


# --- Optimistic concurrency ---------------------------------------------------


def check_version(entity: dict, body: dict):
    """Validate optional `version` body field; raise ERR_VERSION_CONFLICT on mismatch."""
    if not body:
        return
    if "version" not in body:
        return
    ver = body.get("version")
    if ver is None:
        return
    try:
        ver = int(ver)
    except (TypeError, ValueError):
        raise api_error("ERR_VERSION_CONFLICT", "version conflict")
    if ver != entity.get("version"):
        raise api_error("ERR_VERSION_CONFLICT", "version conflict")


# --- JSON body and pagination -------------------------------------------------


def get_json_body() -> dict:
    try:
        body = request.get_json(silent=True) or {}
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    return body


def parse_pagination():
    args = request.args
    try:
        limit = int(args.get("limit", "10"))
        offset = int(args.get("offset", "0"))
    except (TypeError, ValueError):
        raise api_error("ERR_VALIDATION", "invalid limit/offset")
    if limit < 1 or limit > 100 or offset < 0:
        raise api_error("ERR_VALIDATION", "limit out of range or offset negative")
    return limit, offset


def paginate(items, sort_key=None):
    limit, offset = parse_pagination()
    if sort_key is None:
        sort_key = lambda x: (x.get("created_at", ""), x.get("id", ""))
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
