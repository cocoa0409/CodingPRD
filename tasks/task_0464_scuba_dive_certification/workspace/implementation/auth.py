"""Auth header extraction + RBAC (PRD 2.1 / scaffold validations 1,2,5).

Headers (PRD 2.1): X-User-ID, X-User-Role.
Roles (exact spelling): ShopAdmin, Instructor, Diver.
"""
from flask import request

import errors

ROLES = {"ShopAdmin", "Instructor", "Diver"}


class Principal:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_admin(self):
        return self.role == "ShopAdmin"

    @property
    def is_instructor(self):
        return self.role == "Instructor"

    @property
    def is_diver(self):
        return self.role == "Diver"


def authenticate():
    """Validation priority 1: both headers present, role known.
    Returns a Principal or raises ERR_UNAUTHENTICATED (401)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise errors.unauthenticated()
    return Principal(user_id, role)


def require_roles(principal, allowed):
    """Validation priority 2: acting role permitted for this op.
    Raises ERR_FORBIDDEN (403) otherwise."""
    if principal.role not in allowed:
        raise errors.forbidden()
