"""Auth extraction, RBAC, pagination, and request-parsing helpers.

Validation precedence (PRD §2.8):
  1. ERR_UNAUTHENTICATED  — X-User-Role present and a known role; X-User-ID present
  2. ERR_FORBIDDEN_ROLE   — role permitted for this operation
  3. ERR_NOT_RESOURCE_OWNER — ownership for entity-backed roles
  4. ERR_NOT_FOUND        — referenced resources exist (left-to-right)
  5. ERR_INVALID_REQUEST  — body parses, required fields present, types valid
  6. ERR_INVALID_ENUM     — enum membership
  7. ERR_INVALID_PAGINATION — pagination bounds (list endpoints)
  then state & business rules.
"""
from flask import request

import errors
from constants import (
    ROLES,
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_DEFAULT_OFFSET,
    PAGINATION_MAX_LIMIT,
    PAGINATION_MIN_LIMIT,
)


class Auth:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """PRD §2.1: require X-User-ID and X-User-Role; role must be a known role.

    Missing either header, or an unrecognized role, -> ERR_UNAUTHENTICATED.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id == "":
        raise errors.err(errors.ERR_UNAUTHENTICATED, "Missing X-User-ID header")
    if role is None or role == "":
        raise errors.err(errors.ERR_UNAUTHENTICATED, "Missing X-User-Role header")
    if role not in ROLES:
        raise errors.err(errors.ERR_UNAUTHENTICATED, "Unknown X-User-Role")
    return Auth(user_id, role)


def require_role(auth, allowed_roles):
    """PRD §2.1/§2.8: role permitted for this operation -> else ERR_FORBIDDEN_ROLE."""
    if auth.role not in allowed_roles:
        raise errors.err(errors.ERR_FORBIDDEN_ROLE, "Role not permitted for this operation")


def get_json_body():
    """Parse JSON body. Missing/malformed body -> ERR_INVALID_REQUEST.

    An absent body is treated as an empty object so endpoints with no required
    fields succeed.
    """
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Malformed JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Body must be a JSON object")
    return body


def require_fields(body, names):
    for name in names:
        if name not in body or body[name] is None:
            raise errors.err(errors.ERR_INVALID_REQUEST, f"Missing required field: {name}")


def require_string(body, name):
    require_fields(body, [name])
    val = body[name]
    if not isinstance(val, str) or val == "":
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field {name} must be a non-empty string")
    return val


def require_int(body, name):
    require_fields(body, [name])
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field {name} must be an integer")
    return val


def optional_int(body, name, default):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field {name} must be an integer")
    return val


def require_number(body, name):
    require_fields(body, [name])
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field {name} must be a number")
    return float(val)


def optional_number(body, name, default):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field {name} must be a number")
    return float(val)


def optional_bool(body, name, default):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if not isinstance(val, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field {name} must be a boolean")
    return val


def require_enum(body, name, domain):
    """Required enum field: presence (ERR_INVALID_REQUEST) then membership (ERR_INVALID_ENUM)."""
    require_fields(body, [name])
    val = body[name]
    if not isinstance(val, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field {name} must be a string")
    if val not in domain:
        raise errors.err(errors.ERR_INVALID_ENUM, f"Invalid enum value for {name}")
    return val


def parse_pagination():
    """PRD §2.3: limit in [1,100] (default 10), offset >= 0 (default 0).

    Out-of-range -> ERR_INVALID_PAGINATION. Non-integer -> ERR_INVALID_PAGINATION.
    """
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            raise errors.err(errors.ERR_INVALID_PAGINATION, "limit must be an integer")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise errors.err(errors.ERR_INVALID_PAGINATION, "limit out of range [1,100]")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise errors.err(errors.ERR_INVALID_PAGINATION, "offset must be an integer")
        if offset < 0:
            raise errors.err(errors.ERR_INVALID_PAGINATION, "offset must be >= 0")
    return limit, offset


def paginate(records, limit, offset):
    """Sort by created_at asc (PRD §2.3), apply offset/limit, return (page, meta)."""
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta
