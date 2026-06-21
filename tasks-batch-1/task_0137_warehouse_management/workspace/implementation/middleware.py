"""Auth header extraction and RBAC (PRD §2.1, §2.11, scaffold §1.7)."""
from flask import request

from errors import err

VALID_ROLES = {
    "PlatformAdmin",
    "ReceivingClerk",
    "PutawayOperator",
    "Picker",
    "WavePlanner",
    "InventoryController",
}


def get_identity():
    """Return (user_id, role). Raise ERR_UNAUTHENTICATED if headers missing/malformed.

    Required on every mutating request. For GET reads the PRD still expects a
    well-formed authenticated caller (per-endpoint role lists enumerate the six
    roles), so we authenticate on every request and then authorize per endpoint.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise err("ERR_UNAUTHENTICATED", "Missing or malformed X-User-ID header.")
    if not role or role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or malformed X-User-Role header.")
    return user_id, role


def require_roles(role, allowed):
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", "Role '%s' is not permitted for this operation." % role)
