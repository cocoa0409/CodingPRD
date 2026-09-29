"""Authentication and role authorisation (PRD 2.1, validations priority 1 and 2)."""

from flask import g, request

from errors import fail

ROLES = (
    "RealEstateOfficer",
    "ValuationOfficer",
    "BoardSecretary",
    "GrantsComplianceOfficer",
    "TransitOperationsManager",
    "Developer",
    "SystemAdmin",
)

ALL_ROLES = ROLES


def authenticate():
    """Priority 1: X-User-ID and X-User-Role present, role recognised."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED")
    g.user_id = user_id
    g.role = role
    return user_id, role


def authorize(*allowed):
    """Priority 2: the caller's role appears in the endpoint's role list."""
    user_id, role = authenticate()
    if role not in allowed:
        fail("ERR_FORBIDDEN_ROLE", "Role %s may not perform this operation" % role)
    return user_id, role
