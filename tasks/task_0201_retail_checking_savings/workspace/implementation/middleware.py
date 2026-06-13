"""Auth header extraction and RBAC enforcement (PRD §2.1, §2.10)."""
from functools import wraps
from flask import request, g

import errors
from errors import ApiError

# The platform recognizes exactly three roles (PRD §2.1).
VALID_ROLES = {"AccountHolder", "Teller", "ComplianceOfficer"}


def extract_user_context():
    """Validate the two mandatory auth headers (PRD §2.1).

    Returns (user_id, role). Raises ERR_UNAUTHENTICATED (401) when X-User-Role
    is missing or is not one of the recognized roles. X-User-ID is mandatory as
    well; a missing/blank value is likewise unauthenticated.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if role is None or role not in VALID_ROLES:
        raise ApiError(errors.ERR_UNAUTHENTICATED, 401,
                       "Missing or unrecognized X-User-Role header")
    if user_id is None or not isinstance(user_id, str) or user_id.strip() == "":
        raise ApiError(errors.ERR_UNAUTHENTICATED, 401,
                       "Missing X-User-ID header")
    return user_id, role


def require_roles(*allowed_roles):
    """Decorator: enforce auth (401) then role authorization (403)."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = extract_user_context()
            g.user_id = user_id
            g.user_role = role
            if role not in allowed_roles:
                raise ApiError(errors.ERR_FORBIDDEN, 403,
                               "Role not permitted for this operation")
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def get_pagination():
    """Parse limit/offset query params per PRD §2.3.

    limit default 10, min 1, max 100. offset default 0, min 0.
    A non-integer or out-of-domain value is ERR_INVALID_REQUEST (422).
    """
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(errors.ERR_INVALID_REQUEST, 422, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError(errors.ERR_INVALID_REQUEST, 422, "limit out of range [1,100]")

    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(errors.ERR_INVALID_REQUEST, 422, "offset must be an integer")
        if offset < 0:
            raise ApiError(errors.ERR_INVALID_REQUEST, 422, "offset must be >= 0")

    return limit, offset


def paginate(items, limit, offset):
    """Slice a sorted list and return (page, total_count)."""
    total = len(items)
    page = items[offset:offset + limit]
    return page, total
