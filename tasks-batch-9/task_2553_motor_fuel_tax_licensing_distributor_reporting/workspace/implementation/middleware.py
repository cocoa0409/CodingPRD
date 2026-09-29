"""Authentication, role checks and licensee scoping (PRD section 2.1)."""

from flask import request

from errors import ApiError

LICENSEE_AGENT = "LicenseeAgent"
LICENSING_OFFICER = "LicensingOfficer"
RETURNS_EXAMINER = "ReturnsExaminer"
TAX_SUPERVISOR = "TaxSupervisor"
AUDIT_MANAGER = "AuditManager"
FIELD_INSPECTOR = "FieldInspector"

ROLES = (
    LICENSEE_AGENT,
    LICENSING_OFFICER,
    RETURNS_EXAMINER,
    TAX_SUPERVISOR,
    AUDIT_MANAGER,
    FIELD_INSPECTOR,
)

ALL_STAFF = (
    LICENSING_OFFICER,
    RETURNS_EXAMINER,
    TAX_SUPERVISOR,
    AUDIT_MANAGER,
    FIELD_INSPECTOR,
)


def authenticate():
    """Band 1: both identity headers must be present and the role recognised."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise ApiError("ERR_UNAUTHENTICATED")
    user_id = user_id.strip()
    role = role.strip()
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    return user_id, role


def authorize(role, allowed):
    """Band 2: the acting role must appear in the endpoint's role list."""
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED")


def require(*allowed):
    """Authenticate, then authorise against the endpoint's role list."""
    user_id, role = authenticate()
    authorize(role, allowed)
    return user_id, role


def scope_guard(user_id, role, owner_licensee_id):
    """Band 3: a LicenseeAgent may only address its own licensee's rows.

    The header value is compared to the resource's owning licensee id.
    """
    if role != LICENSEE_AGENT:
        return
    if owner_licensee_id is None or str(owner_licensee_id) != str(user_id):
        raise ApiError("ERR_LICENSEE_SCOPE_VIOLATION")


def is_agent(role):
    return role == LICENSEE_AGENT
