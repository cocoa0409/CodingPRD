"""Auth header extraction and role checking (SCAFFOLD validations priority 1-2)."""

from flask import request

from errors import (
    raise_err,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_UNAUTHORIZED,
    ERR_FORBIDDEN,
)

ROLES = {
    "PlatformAdmin",
    "EligibilityAnalyst",
    "COBAnalyst",
    "ClaimsExaminer",
    "RecoverySpecialist",
    "COBAuditor",
    "MemberSelf",
}


def auth_context():
    """Extract and validate X-User-ID / X-User-Role headers.

    Returns (user_id, role). Raises on missing/invalid.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise_err(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-Role or X-User-ID header missing or unrecognized",
        )
    return user_id, role


def require_roles(*allowed):
    """Validate auth headers and require role membership."""
    user_id, role = auth_context()
    if role not in allowed:
        raise_err(ERR_UNAUTHORIZED, "Role is not permitted to invoke this endpoint")
    return user_id, role


def check_member_self_ownership(user_id, role, member_id):
    """MemberSelf: X-User-ID must match the owning member id."""
    if role == "MemberSelf" and user_id != member_id:
        raise_err(ERR_FORBIDDEN, "MemberSelf X-User-ID does not match the resource's owning member")
