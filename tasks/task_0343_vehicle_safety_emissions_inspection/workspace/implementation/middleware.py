"""Auth header extraction and RBAC (PRD §2.1, §2.9)."""
from flask import request

from errors import err

VALID_ROLES = {"StationManager", "Inspector", "Receptionist", "StateAuditor"}


def authenticate():
    """Validate the two mandatory auth headers (PRD §2.1).

    Returns (user_id, role). Raises ERR_UNAUTHENTICATED if either header is
    missing or malformed (empty, or role not one of the four recognized roles).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise err("ERR_UNAUTHENTICATED", "Missing X-User-ID or X-User-Role header.")
    if user_id.strip() == "" or role.strip() == "":
        raise err("ERR_UNAUTHENTICATED", "Empty X-User-ID or X-User-Role header.")
    if role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Unrecognized X-User-Role value.")
    return user_id, role


def authorize(role, allowed_roles):
    """RBAC check (PRD §2.1 / §2.9). Raises ERR_FORBIDDEN if not permitted."""
    if role not in allowed_roles:
        raise err("ERR_FORBIDDEN", "Role %s is not permitted for this operation." % role)
