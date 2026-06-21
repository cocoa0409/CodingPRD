"""Auth header extraction, role checking, ownership checks (PRD §2.1, §2.9)."""
from flask import request

from errors import err
import constants as C


def get_principal():
    """Return (user_id, role) from headers, or (None, None) if absent/malformed.

    Both X-User-ID and X-User-Role must be present and non-empty, and the role
    must be one of the recognized roles."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        return None, None
    if role not in C.ALL_ROLES:
        return None, None
    return user_id, role


def authenticate():
    """Priority 1: X-User-Role and X-User-ID present and well-formed -> else 401."""
    user_id, role = get_principal()
    if user_id is None or role is None:
        raise err("ERR_UNAUTHENTICATED", "Missing or malformed authentication headers")
    return user_id, role


def require_roles(allowed_roles):
    """Priority 1 (auth) then priority 2 (forbidden role). Returns (user_id, role).

    allowed_roles is a set/list of role names permitted for this operation."""
    user_id, role = authenticate()
    if role not in allowed_roles:
        raise err("ERR_FORBIDDEN_ROLE", f"Role {role} is not permitted for this operation")
    return user_id, role


def check_merchant_ownership(role, user_id, owner_merchant_id):
    """Priority 3: a MerchantUser may only act on resources owned by the merchant
    named by X-User-ID. Operators/officers are opaque and skip this check."""
    if role == C.ROLE_MERCHANT and owner_merchant_id != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Resource is not owned by the acting merchant")
