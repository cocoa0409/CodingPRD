"""Auth middleware — reads X-User-ID and X-User-Role per PRD §2.1."""

from flask import request

from .errors import APIError


VALID_ROLES = {
    "DistrictAdmin",
    "SchoolPsychologist",
    "SpecialEducationTeacher",
    "RelatedServiceProvider",
    "Parent",
}


def get_user_context():
    """Return (user_id, role) or raise ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."""
    user_id = request.headers.get("X-User-ID", "")
    role = request.headers.get("X-User-Role", "")
    if not user_id or not role:
        raise APIError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers are required.",
        )
    if role not in VALID_ROLES:
        raise APIError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            f"Unknown role: {role}",
        )
    return user_id, role


def require_role(allowed_roles):
    """Raise ERR_INSUFFICIENT_PERMISSIONS if the caller's role is not in allowed_roles."""
    user_id, role = get_user_context()
    if role not in allowed_roles:
        raise APIError("ERR_INSUFFICIENT_PERMISSIONS", "Role not permitted.")
    return user_id, role
