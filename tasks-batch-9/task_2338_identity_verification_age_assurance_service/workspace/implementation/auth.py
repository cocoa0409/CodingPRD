"""Authentication, RBAC and client-scope enforcement (PRD 2.1, checks 1, 2 and 11)."""
from flask import request

from errors import fail

PLATFORM_ADMIN = "PlatformAdmin"
CLIENT_INTEGRATOR = "ClientIntegrator"
COMPLIANCE_OFFICER = "ComplianceOfficer"
REVIEW_MANAGER = "ReviewManager"
MANUAL_REVIEWER = "ManualReviewer"
INCLUSION_REVIEWER = "InclusionReviewer"

ROLES = (
    PLATFORM_ADMIN,
    CLIENT_INTEGRATOR,
    COMPLIANCE_OFFICER,
    REVIEW_MANAGER,
    MANUAL_REVIEWER,
    INCLUSION_REVIEWER,
)


class Caller:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_client_integrator(self):
        return self.role == CLIENT_INTEGRATOR


def authenticate(allowed_roles):
    """Check 1 (ERR_UNAUTHENTICATED) then check 2 (ERR_ROLE_NOT_PERMITTED)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        fail("ERR_ROLE_NOT_PERMITTED")
    return Caller(user_id, role)


def require_own_client(caller, client_id):
    """Check 11: a ClientIntegrator may only address its own client's resources."""
    if caller.is_client_integrator and client_id != caller.user_id:
        fail("ERR_CLIENT_SCOPE_VIOLATION")
