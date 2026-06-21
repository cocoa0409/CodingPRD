"""Auth header extraction and role checks."""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE

KNOWN_ROLES = {"HrAdmin", "Manager", "Employee", "HrbpPartner", "CompApprover"}


def get_caller():
    """Return (user_id, role). Raise ERR_UNAUTHENTICATED if headers missing/invalid."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or invalid identity headers")
    return user_id, role


def require_role(role, allowed):
    if role not in allowed:
        raise err(ERR_FORBIDDEN_ROLE, "Role not permitted for this operation")
