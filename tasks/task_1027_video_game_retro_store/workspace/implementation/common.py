"""Shared request-handling helpers: auth/RBAC, existence, ownership, body,
and pagination. These enforce the fixed validation precedence (PRD 2.11)."""
from flask import request

from errors import err

ROLES = ("Member", "Clerk", "Manager")


def authorize(allowed_roles):
    """Priority 1 (ERR_UNAUTHENTICATED) then priority 2 (ERR_FORBIDDEN).
    Returns (user_id, role)."""
    role = request.headers.get("X-User-Role")
    if role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid X-User-Role header")
    if role not in allowed_roles:
        raise err("ERR_FORBIDDEN", "Role not permitted for this operation")
    user_id = request.headers.get("X-User-ID")
    return user_id, role


def get_json():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_VALIDATION", "Request body must be a JSON object")
    return body


def require_found(table, key):
    """Priority 3 (ERR_NOT_FOUND). key must be present + resolve."""
    if key is None or key not in table:
        raise err("ERR_NOT_FOUND", "Referenced resource does not exist")
    return table[key]


def check_owner(role, user_id, resource_member_id):
    """Priority 5 (ERR_NOT_RESOURCE_OWNER). Only Members are entity-backed;
    Clerk/Manager are opaque operators and bypass ownership (PRD 2.1)."""
    if role == "Member" and resource_member_id != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Member may only act on own resources")


def parse_pagination():
    """limit default 10 (1..100); offset default 0 (>=0). Out of range or
    non-integer -> ERR_PAGINATION_INVALID (PRD 2.3)."""
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err("ERR_PAGINATION_INVALID", "limit must be an integer")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err("ERR_PAGINATION_INVALID", "offset must be an integer")
    if limit < 1 or limit > 100:
        raise err("ERR_PAGINATION_INVALID", "limit must be between 1 and 100")
    if offset < 0:
        raise err("ERR_PAGINATION_INVALID", "offset must be >= 0")
    return limit, offset


def paginate(records, limit, offset):
    """Sort by creation order (created_at ascending; _seq is the monotonic
    creation counter and breaks any timestamp ties deterministically)."""
    ordered = sorted(records, key=lambda r: r["_seq"])
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return window, total


# --- Body field validators (ERR_VALIDATION, priority 4) -------------------

def need(body, name):
    if name not in body or body[name] is None:
        raise err("ERR_VALIDATION", "Missing required field: " + name)
    return body[name]


def as_str(value, name):
    if not isinstance(value, str) or value == "":
        raise err("ERR_VALIDATION", name + " must be a non-empty string")
    return value


def as_int(value, name):
    # bool is a subclass of int; reject it.
    if isinstance(value, bool) or not isinstance(value, int):
        raise err("ERR_VALIDATION", name + " must be an integer")
    return value


def as_enum(value, name, choices):
    if value not in choices:
        raise err("ERR_VALIDATION", name + " must be one of " + ", ".join(choices))
    return value
