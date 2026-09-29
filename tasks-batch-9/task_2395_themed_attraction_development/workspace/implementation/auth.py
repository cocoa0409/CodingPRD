"""Authentication and role-based access control.

PRD section 2.1: every request must carry X-User-ID and X-User-Role.  The system
recognises exactly seven roles.  A missing header or an unrecognised role yields
ERR_UNAUTHENTICATED (401); a well-formed role that is not listed for the target
endpoint yields ERR_UNAUTHORIZED (403).
"""

from flask import request

from errors import ApiError

OWNER_REP = "OwnerRep"
CREATIVE_DIRECTOR = "CreativeDirector"
RIDE_ENGINEER = "RideEngineer"
SHOW_PROGRAMMER = "ShowProgrammer"
THIRD_PARTY_REVIEWER = "ThirdPartyReviewer"
CONTRACTOR_PM = "ContractorPM"
PROGRAM_ADMIN = "ProgramAdmin"

ALL_ROLES = (
    OWNER_REP,
    CREATIVE_DIRECTOR,
    RIDE_ENGINEER,
    SHOW_PROGRAMMER,
    THIRD_PARTY_REVIEWER,
    CONTRACTOR_PM,
    PROGRAM_ADMIN,
)

READ_ALL = ALL_ROLES


def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401)
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", 403)
    return user_id, role
