"""Auth header extraction and role/ownership checks (PRD section 2.1)."""
from flask import request

from errors import fail

ROLES = {
    "AgentAdmin",
    "Shareholder",
    "TransferExaminer",
    "TransferSupervisor",
    "IssuerOfficer",
    "ComplianceOfficer",
    "ServiceAgent",
}


def auth():
    """Validation priority 1: headers present and role recognized."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "missing or unrecognized X-User-Role / X-User-ID headers")
    return user_id, role


def require_role(role, allowed):
    """Validation priority 2: role must be listed for the endpoint."""
    if role not in allowed:
        fail("ERR_UNAUTHORIZED_ROLE", "role %s is not authorized for this endpoint" % role)


def shareholder_owns(user_id, account_id):
    """Shareholder ownership: X-User-ID must equal the acted-on account id."""
    if account_id != user_id:
        fail("ERR_UNAUTHORIZED_ROLE", "Shareholder may only act on their own account")


def officer_owns(user_id, issuer_id):
    """IssuerOfficer ownership: X-User-ID must equal the acting Issuer id."""
    if issuer_id != user_id:
        fail("ERR_UNAUTHORIZED_ROLE", "IssuerOfficer may only act on their own issuer")
