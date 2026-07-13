"""Authentication (headers), role recognition, authorization, ownership."""

from flask import request

from util import ApiError

ROLES = {"UtilityAdmin", "Tester", "PremisesOwner"}


def authenticate():
    """Return (user_id, role) or raise ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401,
                       "Missing or unrecognized authentication headers")
    return user_id, role


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "Role not permitted for this operation")


def deny():
    raise ApiError("ERR_UNAUTHORIZED", 403, "Ownership check failed")
