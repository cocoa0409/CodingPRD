"""Auth header extraction, role checking, and ownership scoping per PRD §2.1."""

from flask import request

from errors import (
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_UNAUTHORIZED_ROLE,
    ERR_OWNERSHIP_MISMATCH,
    ApiError,
)

ROLES = ("ComplianceAdmin", "Screener", "Landlord", "Applicant")


def get_context():
    """Extract and validate X-User-ID / X-User-Role headers.

    Returns (user_id, role). Raises ApiError when missing or malformed.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers must be present and well-formed",
            400,
        )
    if not role or role not in ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers must be present and well-formed",
            400,
        )
    return user_id, role


def require_role(role, allowed):
    """Stage 2: role admission check."""
    if role not in allowed:
        raise ApiError(
            ERR_UNAUTHORIZED_ROLE,
            "Role in X-User-Role is not permitted on this endpoint",
            403,
        )


def check_landlord_ownership(user_id, role, resource_landlord_id):
    """Stage 4: entity-backed ownership check for Landlord callers."""
    if role == "Landlord" and user_id != resource_landlord_id:
        raise ApiError(
            ERR_OWNERSHIP_MISMATCH,
            "Entity-backed caller does not own the target resource",
            403,
        )


def check_applicant_ownership(user_id, role, resource_applicant_id):
    """Stage 4: entity-backed ownership check for Applicant callers."""
    if role == "Applicant" and user_id != resource_applicant_id:
        raise ApiError(
            ERR_OWNERSHIP_MISMATCH,
            "Entity-backed caller does not own the target resource",
            403,
        )
