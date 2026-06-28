"""Shared request/serialization helpers used across routes."""
from datetime import datetime, timezone

from flask import request

from errors import err

# Pagination defaults (SCAFFOLD response_envelope.pagination_defaults / PRD §2.3)
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0
PAGE_OFFSET_MIN = 0


def get_json_body():
    """Parse JSON body; tolerate empty bodies (return {})."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def serialize(entity):
    """Return a public copy of an entity (strip internal-only fields)."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def parse_pagination():
    """Extract & validate limit/offset → ERR_PAGINATION_INVALID (422) on bad bounds."""
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")

    if limit_raw is None:
        limit = PAGE_LIMIT_DEFAULT
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_PAGINATION_INVALID", "limit must be an integer")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            raise err("ERR_PAGINATION_INVALID", "limit out of bounds")

    if offset_raw is None:
        offset = PAGE_OFFSET_DEFAULT
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_PAGINATION_INVALID", "offset must be an integer")
        if offset < PAGE_OFFSET_MIN:
            raise err("ERR_PAGINATION_INVALID", "offset out of bounds")

    return limit, offset


def paginate(items, limit, offset):
    """Slice a sorted list and return (page_items, pagination_meta)."""
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return page, meta


def sort_by_created(items):
    """Default list sort: created_at ascending, tie-broken by creation sequence."""
    return sorted(items, key=lambda e: (e.get("created_at", ""), e.get("_seq", 0)))


def require_fields(body, fields):
    """Ensure required fields are present (not None) → ERR_INVALID_REQUEST."""
    for f in fields:
        if body.get(f) is None:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % f)


def check_enum(value, allowed, field):
    if value not in allowed:
        raise err("ERR_INVALID_REQUEST", "Invalid value for %s" % field)


def parse_iso8601(value, field):
    """Parse an ISO8601 datetime string into an aware UTC datetime."""
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", "%s must be an ISO8601 string" % field)
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "%s is not a valid ISO8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_from_dt(dt):
    """Format an aware datetime back to ISO8601 UTC with ms precision."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
