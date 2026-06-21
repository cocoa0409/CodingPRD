"""Auth header extraction and role checking per PRD §2.1."""
from flask import request
from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ROLE_OPS = "OpsManager"
ROLE_CASHIER = "Cashier"
ROLE_GUEST = "Guest"
KNOWN_ROLES = {ROLE_OPS, ROLE_CASHIER, ROLE_GUEST}


class Principal:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_ops(self):
        return self.role == ROLE_OPS

    @property
    def is_cashier(self):
        return self.role == ROLE_CASHIER

    @property
    def is_guest(self):
        return self.role == ROLE_GUEST


def authenticate():
    """Validate X-User-ID and X-User-Role. Raises ERR_UNAUTHENTICATED.

    Priority 1: both headers present and X-User-Role is a known role.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or invalid authentication headers")
    return Principal(user_id, role)


def require_role(principal, allowed_roles):
    """Priority 2: acting role must be permitted for this operation."""
    if principal.role not in allowed_roles:
        raise err(ERR_FORBIDDEN, "Role not permitted for this operation")


def forbid():
    raise err(ERR_FORBIDDEN, "Guest may only act on its own resources")
