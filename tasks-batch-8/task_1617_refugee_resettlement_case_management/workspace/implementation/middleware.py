"""Authentication (X-User-ID / X-User-Role) and role authorization."""

from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

CASE_MANAGER = "CaseManager"
HOUSING_COORDINATOR = "HousingCoordinator"
EMPLOYMENT_SPECIALIST = "EmploymentSpecialist"
AGENCY_DIRECTOR = "AgencyDirector"
FEDERAL_OFFICER = "FederalOfficer"

ALL_ROLES = {
    CASE_MANAGER,
    HOUSING_COORDINATOR,
    EMPLOYMENT_SPECIALIST,
    AGENCY_DIRECTOR,
    FEDERAL_OFFICER,
}

# Mapping from X-User-Role to the author_role stamped on CaseNotes.
AUTHOR_ROLE_BY_ROLE = {
    CASE_MANAGER: "CASE_MANAGER",
    HOUSING_COORDINATOR: "HOUSING_COORDINATOR",
    EMPLOYMENT_SPECIALIST: "EMPLOYMENT_SPECIALIST",
    AGENCY_DIRECTOR: "AGENCY_DIRECTOR",
}


def authenticate():
    """Validate the two identity headers; returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ALL_ROLES:
        raise ApiError(
            ERR_UNAUTHENTICATED,
            401,
            "Missing or unrecognized X-User-Role / X-User-ID headers.",
        )
    return user_id, role


def authorize(role, allowed):
    if role not in allowed:
        raise ApiError(
            ERR_FORBIDDEN,
            403,
            "Role not permitted on this endpoint per the RBAC matrix.",
        )
