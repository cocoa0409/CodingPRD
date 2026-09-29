"""Authentication and role gating (PRD 2.1)."""

from flask import request

from errors import ApiError

ROLE_PROGRAM_ADMIN = "ProgramAdmin"
ROLE_PASS_OFFICE_CLERK = "PassOfficeClerk"
ROLE_GATE_AGENT = "GateAgent"
ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"
ROLE_PASSHOLDER = "Passholder"

ALL_ROLES = (
    ROLE_PROGRAM_ADMIN,
    ROLE_PASS_OFFICE_CLERK,
    ROLE_GATE_AGENT,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_PASSHOLDER,
)

USER_HEADER = "X-User-ID"
ROLE_HEADER = "X-User-Role"


def authenticate():
    user_id = request.headers.get(USER_HEADER)
    if user_id is None or user_id.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is required")
    role = request.headers.get(ROLE_HEADER)
    if role is None or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is required")
    role = role.strip()
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is not a recognised role")
    return user_id.strip(), role


def require(*roles):
    """Authenticate then enforce the endpoint's role set."""
    user_id, role = authenticate()
    if roles and role not in roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    return user_id, role
