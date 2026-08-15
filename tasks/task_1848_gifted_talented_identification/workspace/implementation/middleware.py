"""Auth header extraction and role checking per PRD §2.1 / SCAFFOLD validations 1-3."""

from flask import request

from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_GUARDIAN_MISMATCH,
)

VALID_ROLES = {
    "GiftedCoordinator",
    "ReferringEducator",
    "ParentGuardian",
    "CommitteeMember",
    "SpecialEdCoordinator",
}

ALL_ROLES = sorted(VALID_ROLES)


def get_user_context():
    """Extract and validate X-User-ID / X-User-Role. Priority 1 check."""
    user_id = request.headers.get("X-User-ID", "").strip()
    role = request.headers.get("X-User-Role", "").strip()
    if not user_id or not role:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers must be present and non-empty",
            400,
        )
    return user_id, role


def require_roles(*roles):
    """Priority 2 check: role permission for the endpoint."""
    user_id, role = get_user_context()
    if role not in roles:
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            f"Role {role} is not permitted for this endpoint",
            403,
        )
    return user_id, role


def check_guardian_ownership(user_id, student):
    """Priority 3 check: ParentGuardian ownership."""
    if user_id != student.get("primary_guardian_user_id"):
        raise ApiError(
            ERR_GUARDIAN_MISMATCH,
            "X-User-ID does not match the owning student's primary_guardian_user_id",
            403,
        )
