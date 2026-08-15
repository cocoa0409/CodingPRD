"""Auth header extraction and role checking per PRD section 2.1."""

from flask import request

from errors import ApiError

DECLARED_ROLES = {
    "ReleaseManager",
    "QALead",
    "VendorManager",
    "CertificationLead",
    "PlatformReviewer",
    "ComplianceManager",
    "PlatformAdmin",
}


def get_auth():
    """Return (user_id, role) or raise ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in DECLARED_ROLES:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers are required and the role must be declared.",
            400,
        )
    return user_id, role


def require_role(*roles):
    user_id, role = get_auth()
    if role not in roles:
        raise ApiError(
            "ERR_INSUFFICIENT_PERMISSIONS",
            "Role %s may not perform this operation." % role,
            403,
        )
    return user_id, role
