"""Authentication and role-based access control.

PRD 2.1: every request carries X-User-ID and X-User-Role. Exactly five roles
are recognized, spelled precisely:
  SalesAssociate, RentalClerk, AccountsManager, InventoryManager, Contractor

Missing header or unknown role -> ERR_UNAUTHENTICATED (401).
Well-formed headers but role not permitted for the op -> ERR_UNAUTHORIZED (403).

Operator roles (SalesAssociate, RentalClerk, AccountsManager,
InventoryManager) carry an opaque X-User-ID not tied to any entity.
Contractor is entity-backed: X-User-ID is the id of the acting
ContractorAccount.
"""
from flask import request

import errors

ROLES = {
    "SalesAssociate",
    "RentalClerk",
    "AccountsManager",
    "InventoryManager",
    "Contractor",
}


class Caller:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_contractor(self):
        return self.role == "Contractor"


def authenticate():
    """Validate the auth headers; return a Caller or raise ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise errors.unauthenticated()
    return Caller(user_id, role)


def require_roles(caller, allowed_roles):
    """Raise ERR_UNAUTHORIZED unless the caller's role is in allowed_roles."""
    if caller.role not in allowed_roles:
        raise errors.unauthorized()
