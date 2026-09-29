"""Authentication, role authorisation and pagination (PRD 2.1, 2.3, 2.10)."""
from functools import wraps

from flask import g, request

from errors import fail

ROLES = (
    "FinOpsAnalyst",
    "FinOpsController",
    "BusinessUnitOwner",
    "ResourceOwner",
    "PlatformAdmin",
)


def authorize(*allowed_roles):
    """Ladder rungs 1 and 2: header presence then role authorisation."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if user_id is None or str(user_id).strip() == "":
                fail("ERR_UNAUTHENTICATED", "X-User-ID header is missing or empty.")
            if role is None or str(role).strip() == "":
                fail("ERR_UNAUTHENTICATED", "X-User-Role header is missing or empty.")
            if role not in ROLES or role not in allowed_roles:
                fail("ERR_UNAUTHORIZED", "Role %s may not call this endpoint." % role)
            g.user_id = user_id
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def actor():
    return g.get("user_id"), g.get("role")


def user_id():
    return g.get("user_id")


def role():
    return g.get("role")


def pagination():
    """limit defaults to 10 (min 1, max 100); offset defaults to 0."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None and limit_raw != "":
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if offset_raw is not None and offset_raw != "":
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset may not be negative.")
    return limit, offset


def paginate(items):
    limit, offset = pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return page, total, limit, offset
