"""Auth header extraction and role checking (PRD section 2.1, pipeline stages 1 and 3)."""
from flask import request

from errors import ApiError

ROLES = [
    "DesignatedInstitutionalOfficial",
    "ProgramDirector",
    "ProgramCoordinator",
    "Resident",
    "FacultyEvaluator",
    "CCCChair",
]

DIO = "DesignatedInstitutionalOfficial"
PD = "ProgramDirector"
PC = "ProgramCoordinator"
RESIDENT = "Resident"
FACULTY = "FacultyEvaluator"
CCC_CHAIR = "CCCChair"

# Every read endpoint admits all six declared roles.
ANY_ROLE = list(ROLES)


def user_context():
    """Pipeline stage 1: X-User-ID and X-User-Role present, role declared."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            400,
            "Missing or invalid X-User-ID / X-User-Role headers",
        )
    return user_id, role


def require_role(role, allowed):
    """Pipeline stage 3: role must be listed among the endpoint's roles."""
    if role not in allowed:
        raise ApiError(
            "ERR_INSUFFICIENT_PERMISSIONS",
            403,
            "Role not permitted for this endpoint",
        )
