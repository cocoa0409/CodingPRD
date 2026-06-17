"""Auth header extraction and role checking (PRD §2.1, validations priority 1-2)."""
from flask import request

from errors import err

# The four recognised roles (PRD §2.1).
VALID_ROLES = {"HRBP", "FinanceController", "CompensationAnalyst", "HRDirector"}


def get_principal():
    """Extract (user_id, role) from headers. Returns (None, None) if absent."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    return user_id, role


def require_auth(allowed_roles):
    """Validate auth headers and role authorization.

    Priority 1: X-User-Role present and a recognised role -> else
                ERR_UNAUTHENTICATED (401).
    Priority 2: role permitted for the operation -> else ERR_FORBIDDEN (403).

    Identity is opaque: X-User-ID is recorded but never matched to any entity
    (PRD §2.1). It is therefore not required for the auth check, only the role.

    Returns (user_id, role) for the authenticated caller.
    """
    user_id, role = get_principal()
    if not role or role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "missing or unrecognised X-User-Role")
    if role not in allowed_roles:
        raise err("ERR_FORBIDDEN", "role not permitted for this operation")
    return user_id, role
