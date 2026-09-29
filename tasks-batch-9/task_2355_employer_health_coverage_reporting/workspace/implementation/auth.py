"""Ladder rungs 1 and 2: authentication headers and role admission."""

from flask import g, request

from errors import fail

ROLES = (
    "ComplianceOfficer",
    "BenefitsAdmin",
    "Preparer",
    "FilingAgent",
    "EmployeeSelfService",
)

OPERATOR_ROLES = ("ComplianceOfficer", "BenefitsAdmin", "Preparer", "FilingAgent")
ALL_ROLES = ROLES
READ_ROLES = ("ComplianceOfficer", "Preparer", "FilingAgent", "BenefitsAdmin")
READ_ROLES_WITH_EMPLOYEE = (
    "ComplianceOfficer",
    "Preparer",
    "FilingAgent",
    "BenefitsAdmin",
    "EmployeeSelfService",
)


def authenticate():
    """Rung 1 — both headers present, non-empty, role declared."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip():
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
    if not role or not role.strip():
        fail("ERR_UNAUTHENTICATED", "X-User-Role header is required.")
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "Unknown role %r." % role)
    g.user_id = user_id
    g.role = role
    return user_id, role


def require_roles(*allowed):
    """Rungs 1 then 2 — returns (user_id, role)."""
    user_id, role = authenticate()
    if role not in allowed:
        fail("ERR_FORBIDDEN_ROLE", "Role %s may not call this endpoint." % role)
    return user_id, role


def actor():
    return g.user_id
