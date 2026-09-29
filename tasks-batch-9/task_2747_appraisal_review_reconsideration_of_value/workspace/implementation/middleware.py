"""Authentication, role authorization and ownership helpers.

Identity headers (PRD 2.1): X-User-ID and X-User-Role.  Both are required on
every request, reads included.
"""

from flask import request

from errors import fail

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

ROLE_LOAN_OFFICER = "LoanOfficer"
ROLE_AMC_COORDINATOR = "AMCCoordinator"
ROLE_DESK_REVIEWER = "AppraisalDeskReviewer"
ROLE_CHIEF_APPRAISER = "ChiefAppraiser"
ROLE_COMPLIANCE = "ComplianceOfficer"
ROLE_APPRAISER = "Appraiser"
ROLE_BORROWER = "Borrower"

ALL_ROLES = (
    ROLE_LOAN_OFFICER,
    ROLE_AMC_COORDINATOR,
    ROLE_DESK_REVIEWER,
    ROLE_CHIEF_APPRAISER,
    ROLE_COMPLIANCE,
    ROLE_APPRAISER,
    ROLE_BORROWER,
)

# Roles whose X-User-ID is an opaque identifier that resolves to no entity.
OPAQUE_ROLES = (ROLE_LOAN_OFFICER, ROLE_DESK_REVIEWER, ROLE_CHIEF_APPRAISER, ROLE_COMPLIANCE)


def authenticate():
    """Rungs 1 and 2 of the validation ladder."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or user_id.strip() == "":
        fail("ERR_UNAUTHENTICATED")
    if role is None or role.strip() == "":
        fail("ERR_UNAUTHENTICATED")
    if role not in ALL_ROLES:
        fail("ERR_UNAUTHENTICATED")
    return user_id, role


def require_roles(*allowed):
    """Rungs 1-3: authenticate then authorize.  Returns (user_id, role)."""
    user_id, role = authenticate()
    if role not in allowed:
        fail("ERR_FORBIDDEN_ROLE")
    return user_id, role


def require_owner(actual_owner_id, user_id):
    """Rung 4 -- entity backed roles may only act on their own resources."""
    if actual_owner_id != user_id:
        fail("ERR_NOT_RESOURCE_OWNER")
