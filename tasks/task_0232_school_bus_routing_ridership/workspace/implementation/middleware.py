"""Auth header extraction and role checking (PRD §2.1)."""

from flask import request
from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

VALID_ROLES = {"TransportAdmin", "Parent", "Driver"}


class Principal:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """Validate X-User-ID and X-User-Role headers. Returns a Principal.

    Raises ERR_UNAUTHENTICATED when either header is missing or malformed.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise err(ERR_UNAUTHENTICATED, "Missing X-User-ID or X-User-Role header")
    user_id = user_id.strip()
    role = role.strip()
    if not user_id or role not in VALID_ROLES:
        raise err(ERR_UNAUTHENTICATED, "Malformed X-User-ID or X-User-Role header")
    return Principal(user_id, role)


def require_role(principal, allowed_roles):
    """Enforce that the acting role is one of allowed_roles, else ERR_FORBIDDEN."""
    if principal.role not in allowed_roles:
        raise err(ERR_FORBIDDEN, "Role not permitted for this operation")
