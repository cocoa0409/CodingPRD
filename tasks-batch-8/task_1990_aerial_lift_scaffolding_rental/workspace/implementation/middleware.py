"""Auth: X-User-ID / X-User-Role header extraction and role gating."""
from flask import request, g

from errors import ApiError

ROLES = [
    "BranchManager",
    "RentalCoordinator",
    "Driver",
    "YardTechnician",
    "Customer",
]


def get_context():
    """Validate the two auth headers; returns (user_id, role)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401,
                       "X-User-ID and X-User-Role headers are required and role must be declared")
    g.user_id = uid
    g.user_role = role
    return uid, role


def require_roles(allowed):
    role = getattr(g, "user_role", None)
    if role is None:
        raise ApiError("ERR_UNAUTHENTICATED", 401,
                       "X-User-ID and X-User-Role headers are required and role must be declared")
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN", 403,
                       "Role %s is not permitted on this endpoint" % role)


def forbid(message="Ownership check failed"):
    raise ApiError("ERR_FORBIDDEN", 403, message)
