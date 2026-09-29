"""Authentication and role authorisation (PRD 2.1, precedence steps 1 and 2)."""

from flask import request

from errors import ApiError

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

PROGRAM_ADMIN = "ProgramAdmin"
BRIDGE_INSPECTOR = "BridgeInspector"
QA_REVIEWER = "QaReviewer"
RATING_ENGINEER = "RatingEngineer"
DISTRICT_ENGINEER = "DistrictEngineer"
PERMIT_OFFICER = "PermitOfficer"
FHWA_REVIEWER = "FhwaReviewer"

ALL_ROLES = (
    PROGRAM_ADMIN,
    BRIDGE_INSPECTOR,
    QA_REVIEWER,
    RATING_ENGINEER,
    DISTRICT_ENGINEER,
    PERMIT_OFFICER,
    FHWA_REVIEWER,
)

# Roles whose X-User-ID is a Personnel.id.
ENTITY_BACKED_ROLES = (BRIDGE_INSPECTOR, QA_REVIEWER, RATING_ENGINEER, DISTRICT_ENGINEER)


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate(*allowed_roles):
    """Step 1 then step 2 of the global precedence order."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if not user_id or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    if not role or not str(role).strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    role = str(role).strip()
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if allowed_roles and role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    return Actor(str(user_id).strip(), role)


def authenticate_read():
    """Every retrieval and listing operation is available to all seven roles."""
    return authenticate(*ALL_ROLES)
