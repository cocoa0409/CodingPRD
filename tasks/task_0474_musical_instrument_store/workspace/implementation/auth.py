"""Auth header extraction and RBAC enforcement (PRD §2.1, §1.7)."""

from flask import request

from errors import err

ROLES = {"SalesAssociate", "Luthier", "StoreManager", "Customer"}


class Identity:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_customer(self):
        return self.role == "Customer"


def authenticate():
    """Step 1 (priority 1): X-User-Role must be present and a declared role.

    Returns an Identity. Raises ERR_UNAUTHENTICATED otherwise.
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or unrecognized X-User-Role header")
    return Identity(user_id, role)


def require_role(identity, allowed_roles):
    """Step 2 (priority 2): role must be permitted for the operation."""
    if identity.role not in allowed_roles:
        raise err("ERR_FORBIDDEN", "Role %s is not permitted for this operation" % identity.role)
