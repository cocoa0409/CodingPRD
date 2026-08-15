"""Auth header extraction and RBAC (PRD section 2.1, scaffold validations
priorities 1-2 and roles table)."""

from flask import request

from errors import ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED, raise_error

ROLES = ("Consultant", "FacilityManager", "CapitalPlanner", "Approver")


def auth(*allowed_roles):
    """Validate X-User-ID / X-User-Role. When allowed_roles is empty, any of
    the four declared roles is accepted (shared GET endpoints). Returns
    (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise_error(
            ERR_UNAUTHENTICATED,
            "Missing or invalid X-User-Role / X-User-ID headers",
        )
    if allowed_roles and role not in allowed_roles:
        raise_error(
            ERR_UNAUTHORIZED,
            f"Role {role} is not permitted for this endpoint",
        )
    return user_id, role
