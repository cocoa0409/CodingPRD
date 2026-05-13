"""Shared route helpers."""
from flask import request, g
from errors import raise_err
from db import lock


def get_json():
    """Return parsed JSON body or {} for empty."""
    if not request.data:
        return {}
    try:
        body = request.get_json(silent=False, force=False)
    except Exception:
        raise_err("ERR_VALIDATION", "invalid JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_err("ERR_VALIDATION", "body must be an object")
    return body


def parse_int(value, name, minimum=None, maximum=None):
    if value is None:
        raise_err("ERR_VALIDATION", f"{name} required")
    if isinstance(value, bool):
        raise_err("ERR_VALIDATION", f"{name} must be integer")
    if not isinstance(value, int):
        try:
            value = int(value)
        except (ValueError, TypeError):
            raise_err("ERR_VALIDATION", f"{name} must be integer")
    if minimum is not None and value < minimum:
        raise_err("ERR_VALIDATION", f"{name} below minimum")
    if maximum is not None and value > maximum:
        raise_err("ERR_VALIDATION", f"{name} above maximum")
    return value


def parse_pagination():
    args = request.args
    try:
        limit = int(args.get("limit", 10))
    except ValueError:
        raise_err("ERR_VALIDATION", "limit must be integer")
    try:
        offset = int(args.get("offset", 0))
    except ValueError:
        raise_err("ERR_VALIDATION", "offset must be integer")
    if limit < 1 or limit > 100:
        raise_err("ERR_VALIDATION", "limit out of range")
    if offset < 0:
        raise_err("ERR_VALIDATION", "offset below 0")
    return limit, offset


def paginate(items, limit, offset):
    """Return (page_items, pagination_meta)."""
    total = len(items)
    sliced = items[offset: offset + limit]
    return sliced, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }


def sort_by_created(items):
    return sorted(items, key=lambda x: (x.get("created_at"), x.get("_order", 0)))


def require_member_ownership(member_id):
    """If acting role is Member, X-User-ID must equal member_id."""
    if g.user_role == "Member" and g.user_id != member_id:
        raise_err("ERR_FORBIDDEN", "member does not own resource")


def check_occ(obj, body):
    """Optimistic concurrency check: if body['version'] present, compare to obj.version."""
    if "version" in body and body["version"] is not None:
        if body["version"] != obj.get("version"):
            raise_err("ERR_VERSION_CONFLICT", "version conflict")
