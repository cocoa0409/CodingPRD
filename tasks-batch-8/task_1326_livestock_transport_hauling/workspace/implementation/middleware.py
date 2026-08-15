"""Auth: X-User-ID / X-User-Role extraction, role authorization (PRD 2.1)."""
from flask import g, request

from errors import raise_err, ERR_AUTH, ERR_FORBIDDEN_ROLE

ROLES = {
    "CarrierAdmin",
    "Dispatcher",
    "ComplianceOfficer",
    "Driver",
    "ConsigneeAgent",
    "WashoutOperator",
}


def authenticate():
    """Layer 1 of the validation pipeline: identity headers."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise_err(ERR_AUTH, "X-User-ID and a recognized X-User-Role are required")
    g.user_id = uid
    g.user_role = role


def require_role(*roles):
    """Layer 2: role authorization for the endpoint."""
    if g.user_role not in roles:
        raise_err(ERR_FORBIDDEN_ROLE, "role %s may not invoke this endpoint" % g.user_role)
