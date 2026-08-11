"""Auth context extraction and role checking (PRD section 2.1 / 2.9)."""

from flask import request

from errors import ApiError, ERR_AUTH, ERR_FORBIDDEN

ROLES = {
    "Recruiter",
    "ContractAdministrator",
    "CredentialingSpecialist",
    "PracticeManager",
    "FinanceAnalyst",
    "OnboardingDirector",
    "Physician",
    "MentorPhysician",
    "SystemOperator",
}

ALL_ROLES = sorted(ROLES)


def get_context():
    """Priority 1: X-User-ID and X-User-Role present and role declared."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            ERR_AUTH, 400,
            "X-User-ID and X-User-Role headers are required and the role must be declared",
        )
    return user_id, role


def require_role(role, allowed):
    """Priority 2: role is listed on the endpoint."""
    if role not in allowed:
        raise ApiError(ERR_FORBIDDEN, 403, "Role %s is not permitted on this endpoint" % role)


def forbid(message="Entity-backed ownership check failed"):
    raise ApiError(ERR_FORBIDDEN, 403, message)
