"""Auth middleware: extracts X-User-ID / X-User-Role and enforces RBAC."""

from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN, ERR_NOT_OWNER

VALID_ROLES = {
    "Customer",
    "SalesEngineer",
    "CAMOperator",
    "ProcessEngineer",
    "QualityInspector",
    "ProductionPlanner",
    "FabAdmin",
}


def get_auth():
    """Returns (user_id, role). Raises ApiError(401) if headers missing/invalid."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, "Missing or invalid X-User-ID / X-User-Role headers", 401)
    return user_id, role


def require_roles(*allowed_roles):
    """Check that the caller's role is in the allowed set. Returns (user_id, role)."""
    user_id, role = get_auth()
    if role not in allowed_roles:
        raise ApiError(ERR_FORBIDDEN, f"Role {role} is not authorized for this endpoint", 403)
    return user_id, role


def check_customer_ownership(user_id, role, resource_customer_id):
    """For Customer role: verify X-User-ID matches the resource's customer_id."""
    if role == "Customer" and user_id != resource_customer_id:
        raise ApiError(ERR_NOT_OWNER, "Customer does not own this resource", 403)
