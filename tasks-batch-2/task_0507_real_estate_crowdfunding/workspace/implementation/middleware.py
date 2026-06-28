"""Auth header extraction + RBAC (PRD §2.1, §1.7)."""
from flask import request

from errors import err

RECOGNIZED_ROLES = {"FundManager", "ComplianceOfficer", "Operator", "Investor"}


def get_identity():
    """Return (user_id, role). Raises ERR_UNAUTHENTICATED if headers missing/invalid.

    PRD §2.1: every request (except investor registration and anonymous GETs)
    must carry X-User-ID and X-User-Role; X-User-Role must name a recognized role.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in RECOGNIZED_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers")
    return user_id, role


def require_auth():
    return get_identity()


def require_role(allowed_roles):
    """Authenticate, then enforce role membership. Returns (user_id, role)."""
    user_id, role = get_identity()
    if role not in allowed_roles:
        raise err("ERR_FORBIDDEN_ROLE", "Role not permitted for this operation")
    return user_id, role
