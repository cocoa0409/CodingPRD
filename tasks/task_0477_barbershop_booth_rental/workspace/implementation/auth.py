"""Auth header extraction + RBAC (PRD §2.1)."""
from flask import request

import errors

ROLES = {"ShopOwner", "Receptionist", "Barber", "Customer"}


def get_context():
    """Validate X-User-ID / X-User-Role. Raises ERR_MISSING_USER_CONTEXT (401)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or not uid.strip():
        errors.fail(errors.ERR_MISSING_USER_CONTEXT, "Missing or malformed X-User-ID.")
    if not role or role not in ROLES:
        errors.fail(errors.ERR_MISSING_USER_CONTEXT, "Missing or malformed X-User-Role.")
    return uid, role


def require_role(role, allowed):
    """ERR_FORBIDDEN_ROLE (403) when role not in the allowed set."""
    if role not in allowed:
        errors.fail(errors.ERR_FORBIDDEN_ROLE, "Role not permitted for this operation.")
