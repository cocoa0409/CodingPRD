"""Auth context: header extraction and role checking (PRD section 2.1)."""
from flask import request

from errors import (
    ApiError,
    ERR_MISSING_CONTEXT,
    ERR_FORBIDDEN_ROLE,
    ERR_OWNERSHIP,
    raise_err,
)

ROLES = {
    "PlanSponsor",
    "BenefitsAdministrator",
    "ComplianceOfficer",
    "TrustOfficer",
    "Participant",
    "PlatformAdmin",
}

ALL_ROLES = sorted(ROLES)


def user_context():
    """Validate X-User-ID / X-User-Role headers. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID", "")
    role = request.headers.get("X-User-Role", "")
    if not user_id or not user_id.strip() or not role or not role.strip():
        raise_err(
            ERR_MISSING_CONTEXT,
            "X-User-ID and X-User-Role headers are required and must be non-empty",
        )
    if role not in ROLES:
        raise_err(
            ERR_MISSING_CONTEXT,
            f"X-User-Role '{role}' is not a declared role",
        )
    return user_id, role


def require_role(role, allowed):
    if role not in allowed:
        raise_err(
            ERR_FORBIDDEN_ROLE,
            f"Role {role} is not permitted on this endpoint",
        )


def check_participant_ownership(user_id, role, owner_participant_id):
    """When role == Participant, X-User-ID must equal the owning participant id."""
    if role == "Participant" and user_id != owner_participant_id:
        raise_err(
            ERR_OWNERSHIP,
            "Participant caller does not own the target resource",
        )
