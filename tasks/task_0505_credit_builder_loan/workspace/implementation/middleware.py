"""Auth header extraction + RBAC (PRD §2.1, validations priority 1-2).

Two mandatory headers: X-User-ID and X-User-Role. Missing either, or an unknown
role, -> ERR_UNAUTHENTICATED (401). Role not permitted for op -> ERR_FORBIDDEN (403).
"""
from flask import request

from constants import ROLES
from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN


def get_identity():
    """Returns (user_id, role) after validating presence + known role. Raises 401 otherwise."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or invalid authentication headers")
    return user_id, role


def require_role(role, allowed):
    if role not in allowed:
        raise err(ERR_FORBIDDEN, "Role not permitted for this operation")
