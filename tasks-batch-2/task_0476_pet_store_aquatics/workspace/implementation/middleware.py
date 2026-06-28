"""Auth header extraction and role checking (PRD §2.1)."""
from flask import request

from errors import err

# The five recognized roles, spelled precisely (PRD §2.1).
VALID_ROLES = {
    "InventoryManager",
    "LivestockKeeper",
    "ClinicVet",
    "StoreClerk",
    "Customer",
}


def require_auth():
    """Validate X-User-ID and X-User-Role headers (PRD §2.1, precedence step 1).

    Returns (user_id, role). Raises ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER
    when either header is missing or malformed (role not a recognized value).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")
    return user_id, role


def require_role(role, allowed_roles):
    """Role authorization (PRD §2.1, precedence step 2)."""
    if role not in allowed_roles:
        raise err("ERR_INSUFFICIENT_PERMISSIONS")
