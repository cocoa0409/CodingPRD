"""Auth header extraction and role checking per PRD §2.1.

Headers: X-User-ID, X-User-Role.
Roles: PetParent, NutritionVet, BillingAdmin, FulfillmentOps, Anonymous.
"""
from flask import request

import errors

ROLES = {"PetParent", "NutritionVet", "BillingAdmin", "FulfillmentOps", "Anonymous"}


class Caller:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def require_context():
    """Validate the user-context headers (priority 1). Returns a Caller.

    Raises ERR_MISSING_OR_INVALID_USER_CONTEXT (401) when either header is
    missing or X-User-Role is not a recognized role.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        errors.fail(errors.ERR_MISSING_OR_INVALID_USER_CONTEXT)
    return Caller(user_id, role)


def require_role(caller, *allowed_roles):
    """Role authorization (priority 2). Raises ERR_FORBIDDEN_ROLE (403)."""
    if caller.role not in allowed_roles:
        errors.fail(errors.ERR_FORBIDDEN_ROLE)


def require_owner(caller, owner_account_id):
    """Ownership check for PetParent. A PetParent may only act on their own
    account's resources (X-User-ID == owning account_id). Operators (opaque
    roles) are not ownership-restricted.
    """
    if caller.role == "PetParent" and caller.user_id != owner_account_id:
        errors.fail(errors.ERR_FORBIDDEN_ROLE)
