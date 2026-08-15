"""Auth middleware: X-User-ID / X-User-Role validation and role authorization
(PRD section 2.1). Identity is opaque; authorization is purely role-based."""

from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

ROLES = {
    "PlatformAdmin",
    "EnrollmentOfficer",
    "FinanceOfficer",
    "AcademicDirector",
    "ProctorCoordinator",
    "SpecialEdCoordinator",
}

ALL_ROLES = [
    "PlatformAdmin",
    "EnrollmentOfficer",
    "FinanceOfficer",
    "AcademicDirector",
    "ProctorCoordinator",
    "SpecialEdCoordinator",
]


def authenticate(allowed_roles):
    """Validation cascade priority 1 (authentication) then 2 (authorization).
    Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not user_id.strip():
        raise ApiError(
            ERR_UNAUTHENTICATED,
            401,
            "X-User-ID header must be present and non-empty",
        )
    if role is None or role not in ROLES:
        raise ApiError(
            ERR_UNAUTHENTICATED,
            401,
            "X-User-Role header must be present and name one of the declared roles",
        )
    if role not in allowed_roles:
        raise ApiError(
            ERR_UNAUTHORIZED,
            403,
            f"role {role} is not authorized for this endpoint",
        )
    return user_id, role
