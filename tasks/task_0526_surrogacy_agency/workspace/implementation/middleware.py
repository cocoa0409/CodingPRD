"""Auth header extraction and RBAC (PRD §2.1)."""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

VALID_ROLES = {
    "CaseManager",
    "Screener",
    "FinanceOfficer",
    "IntendedParentActor",
    "CarrierActor",
}


def get_identity():
    """Return (user_id, role). Raises ERR_UNAUTHENTICATED if missing/invalid."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or invalid authentication headers")
    return user_id, role


def require_roles(role, allowed):
    if role not in allowed:
        raise err(ERR_FORBIDDEN, "Role %s not permitted for this operation" % role)
