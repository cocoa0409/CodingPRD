"""Auth header extraction and role checks (PRD 2.1, validation priorities 1-2)."""
from flask import request

from errors import raise_error, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ALL_ROLES = [
    "SystemAdmin", "ProjectEngineer", "WorkOrderSupervisor", "Controller",
    "FieldClerk", "RateAnalyst", "Auditor",
]
ROLE_SET = set(ALL_ROLES)

# Mutating methods: X-User-ID required on these (PRD 2.1).
_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class Caller:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


def get_caller() -> Caller:
    """Priority 1: X-User-Role present and one of the seven declared roles;
    X-User-ID present and non-empty on mutating endpoints."""
    role = request.headers.get("X-User-Role", "")
    role = role.strip() if isinstance(role, str) else ""
    user_id = request.headers.get("X-User-ID", "")
    user_id = user_id.strip() if isinstance(user_id, str) else ""
    if not role or role not in ROLE_SET:
        raise_error(ERR_UNAUTHENTICATED, "missing or unknown X-User-Role")
    if request.method in _MUTATING_METHODS and not user_id:
        raise_error(ERR_UNAUTHENTICATED, "missing X-User-ID on a mutating endpoint")
    return Caller(user_id, role)


def authorized(allowed_roles) -> Caller:
    """Priorities 1-2: header presence, then endpoint role membership."""
    caller = get_caller()
    if caller.role not in allowed_roles:
        raise_error(ERR_FORBIDDEN, f"role {caller.role} is not permitted for this endpoint")
    return caller
