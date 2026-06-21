"""Auth header extraction and RBAC enforcement (PRD §2.1, §2.5)."""
from flask import request

from errors import err

VALID_ROLES = {"ResidentAccount", "Dispatcher", "Driver", "Billing"}


def authenticate():
    """Validate X-User-ID and X-User-Role headers. Returns (user_id, role).

    Raises ERR_UNAUTHENTICATED if either is missing or malformed.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or user_id.strip() == "":
        raise err("ERR_UNAUTHENTICATED", "Missing or malformed X-User-ID header.")
    if not role or role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or malformed X-User-Role header.")
    return user_id, role


def require_roles(role, allowed):
    """Raise ERR_FORBIDDEN_ROLE if role is not in the allowed set."""
    if role not in allowed:
        raise err(
            "ERR_FORBIDDEN_ROLE",
            "Role '%s' is not permitted for this operation." % role,
        )


def require_owner(role, user_id, owning_account_id):
    """For an entity-backed ResidentAccount acting on an account-owned resource,
    X-User-ID must equal the owning account's id (PRD §2.1, validation priority 3).
    Operator roles are opaque and are never compared.
    """
    if role == "ResidentAccount" and user_id != owning_account_id:
        raise err(
            "ERR_NOT_RESOURCE_OWNER",
            "Resident does not own the targeted resource.",
        )
