"""Auth header extraction and role checking."""

from flask import request

from errors import ApiError, ERR_AUTH, ERR_FORBIDDEN

ROLES = [
    "PI",
    "PreAwardAnalyst",
    "DepartmentChair",
    "ComplianceOfficer",
    "SubrecipientManager",
    "OSPDirector",
    "OSPSystemAdmin",
]

ALL_ROLES = list(ROLES)


def authenticate():
    """Validate X-User-ID / X-User-Role headers. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            ERR_AUTH, 400,
            "X-User-ID and X-User-Role headers are required and the role must "
            "be one of the seven declared roles")
    return user_id, role


def require_roles(allowed):
    """Authenticate, then enforce the endpoint's role list."""
    user_id, role = authenticate()
    if role not in allowed:
        raise ApiError(
            ERR_FORBIDDEN, 403,
            "Role %s is not permitted to perform this operation" % role)
    return user_id, role
