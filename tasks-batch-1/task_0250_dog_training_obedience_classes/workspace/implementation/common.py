"""Auth, validation helpers, pagination, and shared utilities."""
from flask import request

from errors import err
from store import db, now_iso

VALID_ROLES = {"Owner", "Trainer", "FrontDesk", "AdminManager"}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def get_user_context():
    """Validate and return (user_id, role). Raises on missing/invalid headers."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "X-User-ID and X-User-Role headers must be present and valid")
    return user_id, role


def require_role(role, allowed):
    if role not in allowed:
        raise err("ERR_INSUFFICIENT_PERMISSIONS",
                  "Role %s is not permitted for this operation" % role)


# ---------------------------------------------------------------------------
# Body parsing / field validation
# ---------------------------------------------------------------------------
def get_json_body():
    if request.method in ("POST", "PATCH", "PUT"):
        if request.data and len(request.data) > 0:
            try:
                body = request.get_json(force=True, silent=True)
            except Exception:
                raise err("ERR_INVALID_REQUEST", "Malformed JSON body")
            if body is None:
                raise err("ERR_INVALID_REQUEST", "Malformed JSON body")
            if not isinstance(body, dict):
                raise err("ERR_INVALID_REQUEST", "Body must be a JSON object")
            return body
        return {}
    return {}


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % f)


def check_string(body, field, required=True):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
        return None
    val = body[field]
    if not isinstance(val, str):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a string" % field)
    return val


def check_enum(body, field, allowed, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
        return default
    val = body[field]
    if not isinstance(val, str) or val not in allowed:
        raise err("ERR_INVALID_REQUEST",
                  "Field %s must be one of %s" % (field, sorted(allowed)))
    return val


def check_int(body, field, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer" % field)
    return val


def check_bool(body, field, required=False, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a boolean" % field)
    return val


def check_array(body, field, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
        return default
    val = body[field]
    if not isinstance(val, list):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an array" % field)
    return val


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def parse_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(items, limit, offset):
    """items already sorted. Returns (page_items, pagination_meta)."""
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


def sorted_by_created(values):
    return sorted(values, key=lambda r: (r["created_at"], r["id"]))


# ---------------------------------------------------------------------------
# Mutation helpers
# ---------------------------------------------------------------------------
def touch(entity):
    """Advance updated_at and version on a mutated entity (if it carries them)."""
    if "version" in entity:
        entity["version"] = entity["version"] + 1
    if "updated_at" in entity:
        entity["updated_at"] = now_iso()
