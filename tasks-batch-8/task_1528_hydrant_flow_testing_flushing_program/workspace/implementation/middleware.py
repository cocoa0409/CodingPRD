"""Auth header extraction and role checking (validation priorities 1 and 3)."""
from flask import request

from errors import (
    ApiError,
    ERR_FORBIDDEN_ROLE,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
)

ALL_ROLES = {
    "ProgramAdmin",
    "FieldOperator",
    "UtilitySupervisor",
    "FireDeptLiaison",
    "PrivateOwnerRep",
}


def auth():
    """Priority 1: X-User-ID and X-User-Role must be present and non-empty."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or not user_id.strip() or not role.strip():
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers must be present and non-empty",
            400,
        )
    return user_id, role


def require_role(role, allowed):
    """Priority 3: the role must be in the endpoint's authorized role list."""
    if role not in allowed:
        raise ApiError(
            ERR_FORBIDDEN_ROLE,
            "Role %s is not permitted for this endpoint" % role,
            403,
        )


def auth_any():
    """Auth for endpoints open to every recognized role (all GET endpoints)."""
    user_id, role = auth()
    require_role(role, ALL_ROLES)
    return user_id, role
