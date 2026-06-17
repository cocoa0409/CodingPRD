"""Auth header extraction and role/ownership checking (PRD §2.1, §2.6)."""
from flask import request

from errors import (
    ERR_FORBIDDEN,
    ERR_UNAUTHENTICATED,
    err,
)

# The system recognizes exactly five roles (PRD §2.1).
KNOWN_ROLES = {
    "DispatchAdmin",
    "Dispatcher",
    "CorporateBooker",
    "AffiliatePartner",
    "Chauffeur",
}


def authenticate():
    """Validate the two mandatory headers (PRD §2.1).

    X-User-ID and X-User-Role must both be present and X-User-Role must name a
    known role; otherwise ERR_UNAUTHENTICATED. Returns (user_id, role).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or invalid authentication headers")
    return user_id, role


def require_role(role, allowed):
    """RBAC: the acting role must be permitted for this operation (PRD §2.6).

    `allowed` is the endpoint's role list. ERR_FORBIDDEN otherwise.
    """
    if role not in allowed:
        raise err(ERR_FORBIDDEN, "Role not permitted for this operation")
