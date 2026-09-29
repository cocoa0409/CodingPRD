"""Authentication and role permission (PRD section 2.1, ordering steps 1-2)."""

from flask import request

from errors import raise_error

ROLES = (
    "ProgramAdmin",
    "IntakeSpecialist",
    "ComplianceOfficer",
    "SafetyDirector",
    "FieldAuditor",
    "PenaltyCounsel",
    "RetailerRep",
)

USER_HEADER = "X-User-ID"
ROLE_HEADER = "X-User-Role"


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    user_id = request.headers.get(USER_HEADER)
    role = request.headers.get(ROLE_HEADER)
    if user_id is None or str(user_id).strip() == "":
        raise_error("ERR_UNAUTHENTICATED")
    if role is None or str(role).strip() == "":
        raise_error("ERR_UNAUTHENTICATED")
    if role not in ROLES:
        raise_error("ERR_UNAUTHENTICATED")
    return Actor(user_id, role)


def authorize(*allowed):
    """Step 1 then step 2: authenticate, then check the endpoint's role list."""
    actor = authenticate()
    if actor.role not in allowed:
        raise_error("ERR_ROLE_NOT_PERMITTED")
    return actor


ALL_ROLES = ROLES
