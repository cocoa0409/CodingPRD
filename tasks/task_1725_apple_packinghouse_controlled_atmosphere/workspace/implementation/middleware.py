"""Auth header extraction and role checks (PRD 2.1, validation tiers 1-3).

Identity semantics: for Admin/ReceivingClerk/StorageOperator/PackingSupervisor/
PoolManager the X-User-ID is an opaque operator id; for Grower it is the id of
the acting Grower entity and ownership checks compare against it.
"""
from flask import request

from errors import (
    raise_error,
    ERR_UNAUTHENTICATED,
    ERR_FORBIDDEN,
    ERR_GROWER_SCOPE_VIOLATION,
)

ALL_ROLES = {
    "Admin",
    "ReceivingClerk",
    "StorageOperator",
    "PackingSupervisor",
    "PoolManager",
    "Grower",
}


class Caller:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


def get_caller() -> Caller:
    """Tier 1: headers present and the role is one of the six declared roles."""
    user_id = request.headers.get("X-User-ID", "").strip()
    role = request.headers.get("X-User-Role", "").strip()
    if not user_id or not role or role not in ALL_ROLES:
        raise_error(ERR_UNAUTHENTICATED,
                    "X-User-ID and X-User-Role headers are required and the role must be recognized")
    return Caller(user_id, role)


def check_role_allowed(caller: Caller, allowed_roles):
    """Tier 2: role membership in the endpoint's declared role list."""
    if caller.role not in allowed_roles:
        raise_error(ERR_FORBIDDEN,
                    f"role {caller.role} is not permitted for this endpoint")


def authorized(allowed_roles) -> Caller:
    """Tiers 1-2 for a request."""
    caller = get_caller()
    check_role_allowed(caller, allowed_roles)
    return caller


def check_grower_scope(caller: Caller, grower_id):
    """Tier 3: a Grower caller may address only its own records."""
    if caller.role != "Grower":
        return
    if grower_id is None:
        return
    if caller.user_id != grower_id:
        raise_error(ERR_GROWER_SCOPE_VIOLATION,
                    "grower caller addressed a resource owned by a different grower")
