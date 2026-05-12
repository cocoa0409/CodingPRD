"""Auth header extraction and role checking."""
from flask import request

from errors import (
    APIError,
    ERR_FORBIDDEN,
    ERR_UNAUTHENTICATED,
    raise_err,
)


VALID_ROLES = {"SiteManager", "PlanOwner", "Dispatcher", "Technician", "Storekeeper"}


def require_auth():
    """Validate X-User-ID and X-User-Role headers.

    Returns (role, user_id). Raises ERR_UNAUTHENTICATED if either header is missing/empty.
    """
    role = request.headers.get("X-User-Role", "").strip()
    user_id = request.headers.get("X-User-ID", "").strip()
    if not role or not user_id:
        raise_err(ERR_UNAUTHENTICATED, "Missing X-User-ID or X-User-Role")
    return role, user_id


def require_role(allowed_roles):
    """Authenticate caller and ensure their role is in allowed_roles.

    `allowed_roles` may include the pseudo-role "Any" which allows any
    authenticated role.

    Returns (role, user_id).
    """
    role, user_id = require_auth()
    if "Any" in allowed_roles:
        return role, user_id
    if role not in allowed_roles:
        raise_err(ERR_FORBIDDEN, f"Role {role} is not permitted")
    return role, user_id
