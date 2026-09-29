"""Authentication and role-based access control (PRD 2.1).

Every request except the two clock endpoints must carry X-User-ID and
X-User-Role.  The check runs before anything else at all -- before path
parameters are parsed, before the body is inspected -- and both headers are
required together.
"""

from flask import request

from errors import fail

AGENCY_PRINCIPAL = "AgencyPrincipal"
PLACEMENT_CONSULTANT = "PlacementConsultant"
VETTING_SPECIALIST = "VettingSpecialist"
BILLING_ADMINISTRATOR = "BillingAdministrator"
COMPLIANCE_OFFICER = "ComplianceOfficer"
CLIENT = "Client"
CANDIDATE = "Candidate"

ALL_ROLES = (
    AGENCY_PRINCIPAL,
    PLACEMENT_CONSULTANT,
    VETTING_SPECIALIST,
    BILLING_ADMINISTRATOR,
    COMPLIANCE_OFFICER,
    CLIENT,
    CANDIDATE,
)

KNOWN_ROLES = set(ALL_ROLES)


def authenticate(allowed_roles):
    """Return (user_id, role) or raise the appropriate auth error.

    `allowed_roles` is the exact set of roles the PRD section 4 endpoint table
    grants for this operation.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")

    if user_id is None or not str(user_id).strip():
        fail("ERR_MISSING_AUTH_HEADER")
    if role is None or not str(role).strip():
        fail("ERR_MISSING_AUTH_HEADER")

    role = str(role)
    if role not in KNOWN_ROLES:
        fail("ERR_INVALID_ROLE")

    if role not in allowed_roles:
        fail("ERR_UNAUTHORIZED")

    return str(user_id), role
