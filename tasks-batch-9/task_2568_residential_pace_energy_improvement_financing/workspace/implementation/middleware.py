"""Auth header extraction, RBAC and row-ownership checks (PRD 2.1, 2.6)."""

from flask import request

from errors import fail

ROLE_PROPERTY_OWNER = "PropertyOwner"
ROLE_CONTRACTOR = "Contractor"
ROLE_UNDERWRITING_ANALYST = "UnderwritingAnalyst"
ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"
ROLE_FUNDING_OFFICER = "FundingOfficer"
ROLE_COUNTY_OFFICER = "CountyOfficer"
ROLE_PROGRAM_ADMIN = "ProgramAdmin"

ALL_ROLES = [
    ROLE_PROPERTY_OWNER,
    ROLE_CONTRACTOR,
    ROLE_UNDERWRITING_ANALYST,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_FUNDING_OFFICER,
    ROLE_COUNTY_OFFICER,
    ROLE_PROGRAM_ADMIN,
]

# The two identity-bearing roles: their X-User-ID is the primary key of a row.
IDENTITY_ROLES = (ROLE_PROPERTY_OWNER, ROLE_CONTRACTOR)


class Caller(object):
    def __init__(self, role, user_id):
        self.role = role
        self.user_id = user_id

    @property
    def is_owner_role(self):
        return self.role == ROLE_PROPERTY_OWNER

    @property
    def is_contractor_role(self):
        return self.role == ROLE_CONTRACTOR


def _header(name):
    value = request.headers.get(name)
    if value is None:
        return None
    return value


def authorize(allowed_roles):
    """Ladder stage 1 (401) then stage 2 (403)."""
    role = _header("X-User-Role")
    if role is None or not role.strip():
        # Structural fallback: some spec text spells the role header X-Role.
        role = _header("X-Role")
    if role is None or not role.strip():
        fail("ERR_MISSING_AUTH_HEADER", "X-User-Role header is required")
    role = role.strip()

    user_id = _header("X-User-ID")
    identity_required = any(candidate in IDENTITY_ROLES for candidate in allowed_roles)
    if identity_required and (user_id is None or not user_id.strip()):
        fail("ERR_MISSING_AUTH_HEADER", "X-User-ID header is required")
    if user_id is not None:
        user_id = user_id.strip()

    if role not in allowed_roles:
        fail("ERR_UNAUTHORIZED", "Role %s may not perform this operation" % role)

    return Caller(role, user_id)


def require_property_owner(caller, property_id):
    """Ladder stage 6 for a PropertyOwner acting on a parcel."""
    if caller.is_owner_role and caller.user_id != property_id:
        fail("ERR_NOT_RESOURCE_OWNER", "Caller does not own this parcel")


def require_contractor(caller, contractor_id):
    """Ladder stage 6 for a Contractor acting through an application."""
    if caller.is_contractor_role and caller.user_id != contractor_id:
        fail("ERR_NOT_RESOURCE_OWNER", "Caller is not the contractor on this application")
