"""Auth header extraction and RBAC (PRD §2.1, SCAFFOLD §1.4 priority 1-2)."""
from flask import request

import errors

ROLES = {"StaffManager", "Member"}


class Caller:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_staff(self):
        return self.role == "StaffManager"

    @property
    def is_member(self):
        return self.role == "Member"


def authenticate():
    """Priority 1: both headers present and X-User-Role a declared role.

    PRD §2.1: X-User-ID identifies the acting user, X-User-Role declares the
    role. Missing either, or an unrecognized role -> ERR_UNAUTHENTICATED (401).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        errors.raise_error(errors.ERR_UNAUTHENTICATED, "Missing or invalid authentication headers")
    return Caller(user_id, role)


def require_role(caller, allowed_roles):
    """Priority 2: acting role permitted for the endpoint -> else ERR_UNAUTHORIZED."""
    if caller.role not in allowed_roles:
        errors.raise_error(errors.ERR_UNAUTHORIZED, "Role not permitted for this operation")


def require_owner(caller, owner_member_id):
    """Member ownership check (PRD §2.1).

    A StaffManager bypasses ownership. A Member must own the resource:
    the resource's member foreign key must equal X-User-ID.
    """
    if caller.is_staff:
        return
    if caller.user_id != owner_member_id:
        errors.raise_error(errors.ERR_UNAUTHORIZED, "Member may only act on their own resources")
