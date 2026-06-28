"""Auth context, RBAC, and ownership (PRD §2.1, §3.12).

Headers (PRD §2.1):
  X-User-ID   — acting user (Driver.id for DriverUser; opaque for the other two)
  X-User-Role — DriverUser | UnderwritingOps | ClaimsAdjuster
"""
from flask import request

from errors import ApiError

ROLES = {"DriverUser", "UnderwritingOps", "ClaimsAdjuster"}


def auth_context():
    """Validate the two mandatory headers (PRD §2.1). Returns (user_id, role).

    Missing/malformed -> ERR_MISSING_USER_CONTEXT (401). An unrecognized role
    value is malformed user context per §2.1 ("carrying a malformed value").
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise ApiError("ERR_MISSING_USER_CONTEXT")
    if not role or role not in ROLES:
        raise ApiError("ERR_MISSING_USER_CONTEXT")
    return user_id, role


def require_role(role, allowed):
    """ERR_FORBIDDEN_ROLE (403) when the declared role is not in `allowed`."""
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN_ROLE")


def require_owner(role, user_id, driver_id):
    """Ownership check (PRD §2.1, priority 3). A DriverUser acting on a
    driver-scoped resource must be the owning driver. Opaque roles are exempt."""
    if role == "DriverUser" and driver_id is not None and user_id != driver_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
