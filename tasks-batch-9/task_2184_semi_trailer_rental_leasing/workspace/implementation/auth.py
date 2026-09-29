"""Authentication and role authorisation (PRD sections 2.1 and 2.9 steps 1-2)."""

from flask import request

from errors import fail

ROLES = ("FleetAdmin", "BranchManager", "Inspector", "ChargebackApprover", "Customer")
ALL_ROLES = list(ROLES)


class Caller(object):
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_admin(self):
        return self.role == "FleetAdmin"

    @property
    def is_branch_manager(self):
        return self.role == "BranchManager"

    @property
    def is_customer(self):
        return self.role == "Customer"


def authenticate(allowed_roles):
    """Step 1: headers.  Step 2: role authorisation."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "Valid X-User-ID and X-User-Role headers are required")
    if role not in allowed_roles:
        fail("ERR_FORBIDDEN_ROLE", "Role %s may not call this endpoint" % role)
    return Caller(user_id, role)


def require_owner(caller, expected_id):
    """Step 8: ownership for entity-backed callers."""
    if caller.user_id != expected_id:
        fail("ERR_NOT_RESOURCE_OWNER", "Caller does not own this resource")
