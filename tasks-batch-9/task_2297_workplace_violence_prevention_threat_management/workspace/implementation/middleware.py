"""Authentication / authorisation (PRD 2.1) -- precedence steps 1, 2 and 3."""

from flask import request

from db import store
from errors import ApiError

ROLE_SAFETY_OFFICER = "SafetyOfficer"
ROLE_SITE_MANAGER = "SiteManager"
ROLE_THREAT_TEAM_LEAD = "ThreatTeamLead"
ROLE_THREAT_TEAM_MEMBER = "ThreatTeamMember"
ROLE_SECURITY_COORDINATOR = "SecurityCoordinator"
ROLE_HR_PARTNER = "HRPartner"
ROLE_EMPLOYEE = "Employee"
ROLE_COMPLIANCE_AUDITOR = "ComplianceAuditor"
ROLE_ANONYMOUS = "Anonymous"
ROLE_PROGRAM_ADMIN = "ProgramAdmin"

ALL_ROLES = (
    ROLE_SAFETY_OFFICER,
    ROLE_SITE_MANAGER,
    ROLE_THREAT_TEAM_LEAD,
    ROLE_THREAT_TEAM_MEMBER,
    ROLE_SECURITY_COORDINATOR,
    ROLE_HR_PARTNER,
    ROLE_EMPLOYEE,
    ROLE_COMPLIANCE_AUDITOR,
    ROLE_ANONYMOUS,
    ROLE_PROGRAM_ADMIN,
)

ENTITY_BACKED_ROLES = (
    ROLE_SAFETY_OFFICER,
    ROLE_SITE_MANAGER,
    ROLE_THREAT_TEAM_LEAD,
    ROLE_THREAT_TEAM_MEMBER,
    ROLE_SECURITY_COORDINATOR,
    ROLE_HR_PARTNER,
    ROLE_EMPLOYEE,
)


class Caller(object):
    __slots__ = ("user_id", "role", "employee")

    def __init__(self, user_id, role, employee):
        self.user_id = user_id
        self.role = role
        self.employee = employee


def authenticate(allowed_roles):
    """Steps 1-3 of the rejection precedence."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")

    # Step 1 -- headers present and the role is one of the ten known strings.
    if role is None or role == "" or role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or unrecognised X-User-Role header.")
    if role != ROLE_ANONYMOUS and (user_id is None or user_id == ""):
        raise ApiError("ERR_UNAUTHENTICATED", "Missing X-User-ID header.")

    # Step 2 -- the role must be listed for this endpoint.
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", "Role %s may not call this endpoint." % role)

    # Step 3 -- entity-backed roles must resolve to an ACTIVE Employee.
    employee = None
    if role in ENTITY_BACKED_ROLES:
        employee = store.employees.get(user_id)
        if employee is None or employee["employment_status"] != "ACTIVE":
            raise ApiError(
                "ERR_UNAUTHORIZED",
                "X-User-ID does not resolve to an ACTIVE employee.",
            )

    return Caller(user_id, role, employee)
