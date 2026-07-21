"""Authentication, authorization, ownership, and request-parsing helpers."""
from flask import request

from constants import (
    HEADER_USER_ID,
    HEADER_USER_ROLE,
    KNOWN_ROLES,
    ROLE_MEMBER,
    PAGE_LIMIT_DEFAULT,
    PAGE_LIMIT_MIN,
    PAGE_LIMIT_MAX,
    PAGE_OFFSET_DEFAULT,
)
from errors import err


class Ctx:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_member(self):
        return self.role == ROLE_MEMBER


def authenticate():
    """Validate the two mandatory headers. Priority 1 (ERR_UNAUTHENTICATED)."""
    user_id = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    if not user_id or not role or role not in KNOWN_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers")
    return Ctx(user_id, role)


def authorize(ctx, allowed_roles):
    """Priority 2 (ERR_UNAUTHORIZED)."""
    if ctx.role not in allowed_roles:
        raise err("ERR_UNAUTHORIZED", "Role not permitted for this operation")


def require_ownership(ctx, owner_id):
    """Priority 4 (ERR_FORBIDDEN_OWNERSHIP). Only members are checked."""
    if ctx.is_member and ctx.user_id != owner_id:
        raise err("ERR_FORBIDDEN_OWNERSHIP", "Member does not own this resource")


# ---- Request body parsing ----

def body_json():
    raw = request.get_data(as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise err("ERR_VALIDATION", "Malformed request body")
    return data


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_VALIDATION", f"Missing required field: {f}")


def get_str(body, field, required=True):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_VALIDATION", f"Missing required field: {field}")
        return None
    val = body[field]
    if not isinstance(val, str) or val == "":
        raise err("ERR_VALIDATION", f"Field {field} must be a non-empty string")
    return val


def get_enum(body, field, choices, required=True):
    val = get_str(body, field, required=required)
    if val is None:
        return None
    if val not in choices:
        raise err("ERR_VALIDATION", f"Field {field} has an invalid value")
    return val


def get_int(body, field, required=True, minimum=None, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_VALIDATION", f"Missing required field: {field}")
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_VALIDATION", f"Field {field} must be an integer")
    if minimum is not None and val < minimum:
        raise err("ERR_VALIDATION", f"Field {field} must be >= {minimum}")
    return val


def get_bool(body, field, required=False, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_VALIDATION", f"Missing required field: {field}")
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise err("ERR_VALIDATION", f"Field {field} must be a boolean")
    return val


# ---- Pagination ----

def parse_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = PAGE_LIMIT_DEFAULT
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_VALIDATION", "limit must be an integer")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            raise err("ERR_VALIDATION", "limit out of range")
    if offset_raw is None:
        offset = PAGE_OFFSET_DEFAULT
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_VALIDATION", "offset must be an integer")
        if offset < 0:
            raise err("ERR_VALIDATION", "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    return items[offset:offset + limit]
