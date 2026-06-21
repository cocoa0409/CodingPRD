"""Auth header extraction and role checking (PRD §2.1)."""
from flask import request

from errors import err

KNOWN_ROLES = {"Customer", "LotOperator", "FacilityAdmin"}


def get_principal():
    """Return (user_id, role) after validating presence and known role.

    Raises ERR_UNAUTHENTICATED if X-User-ID is missing, X-User-Role is missing,
    or X-User-Role does not name a recognized role.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise err("ERR_UNAUTHENTICATED")
    return user_id, role


def require_roles(role, allowed):
    """Raise ERR_FORBIDDEN_ROLE if role is not in the allowed set."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE")
