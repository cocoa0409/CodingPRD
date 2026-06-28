"""Auth header extraction and RBAC helpers (PRD §2.1)."""
from flask import request

import errors

VALID_ROLES = {"BillingAdmin", "ScreeningOfficer", "Matchmaker", "Member"}


class Principal:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """Extract and validate X-User-ID / X-User-Role headers.

    Raises ERR_UNAUTHENTICATED if either header is missing or malformed.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise errors.unauthenticated()
    if not role or role not in VALID_ROLES:
        raise errors.unauthenticated()
    return Principal(user_id.strip(), role)


def require_roles(principal, allowed_roles):
    """Role gate. Raises ERR_FORBIDDEN if the principal's role is not allowed."""
    if principal.role not in allowed_roles:
        raise errors.forbidden()


def require_member_owner(principal, owner_member_id):
    """Ownership gate for the entity-backed Member role.

    Operator roles bypass ownership (their identity is opaque). The Member role
    must have X-User-ID equal to the resource's owning member id.
    """
    if principal.role == "Member" and principal.user_id != owner_member_id:
        raise errors.forbidden()
