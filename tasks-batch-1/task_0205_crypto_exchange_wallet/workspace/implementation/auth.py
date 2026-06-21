"""Auth header extraction and RBAC (§2.1, §1.7)."""
from flask import request

from errors import err

ROLES = {"Anonymous", "Trader", "Operator", "ComplianceOfficer"}


def get_identity():
    """Return (user_id, role). Raises ERR_UNAUTHENTICATED when headers are
    missing or the role is unknown. Used by all protected endpoints."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers")
    return user_id, role


def require_roles(role, allowed):
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", "Role %s is not permitted for this operation" % role)
