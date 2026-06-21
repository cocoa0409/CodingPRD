"""Auth header extraction & RBAC (PRD §2.1, §2.10; SCAFFOLD §1.4, §1.7)."""
from flask import request

import errors

VALID_ROLES = {"NetworkAdmin", "LoungeAgent", "Member"}


def get_principal():
    """Return (user_id, role). Raises ERR_UNAUTHENTICATED when the role header is
    missing or not one of the three known roles (PRD §2.1)."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in VALID_ROLES:
        raise errors.unauthenticated("Missing or unknown X-User-Role")
    # X-User-ID must be present for all roles (the acting principal id).
    if user_id is None:
        raise errors.unauthenticated("Missing X-User-ID")
    return user_id, role


def require_role(role, allowed):
    """Priority-2 RBAC check: ERR_FORBIDDEN_ROLE when role not in allowed set."""
    if role not in allowed:
        raise errors.forbidden_role(
            "Role %s not permitted for this operation" % role
        )
