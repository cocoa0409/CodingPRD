"""Auth header extraction and RBAC (PRD §2.1, §3.12).

Two mandatory headers: X-User-ID and X-User-Role.
Recognized roles, spelled exactly: AccountManager, FieldTech, Dispatcher,
CustomerOwner.
"""

from flask import request

from errors import ApiError

VALID_ROLES = {"AccountManager", "FieldTech", "Dispatcher", "CustomerOwner"}


def get_auth():
    """Validate both headers are present and well-formed. (priority 1)

    Returns (user_id, role). Raises ERR_UNAUTHENTICATED otherwise.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or malformed X-User-ID header.")
    if not role or role not in VALID_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or malformed X-User-Role header.")
    return user_id, role


def require_roles(role, allowed):
    """RBAC check (priority 2). Raise ERR_FORBIDDEN_ROLE if not permitted."""
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN_ROLE", "Acting role is not permitted for this endpoint.")
