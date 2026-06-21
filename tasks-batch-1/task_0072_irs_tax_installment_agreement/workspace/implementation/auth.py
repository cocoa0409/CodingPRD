from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE

ROLES = {"RevenueOfficer", "CaseReviewer"}


def get_identity():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or invalid authentication headers")
    return user_id, role


def authorize(allowed_roles):
    """Validate auth headers and role membership. Returns (user_id, role)."""
    user_id, role = get_identity()
    if role not in allowed_roles:
        raise err(ERR_FORBIDDEN_ROLE, "Role not permitted for this operation")
    return user_id, role
