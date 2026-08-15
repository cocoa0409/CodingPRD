"""Auth header extraction, role admission, and Contractor ownership checks
(PRD 2.1, validation priorities 1-2)."""
from flask import request

from errors import (
    raise_error,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_FORBIDDEN,
)

ALL_ROLES = [
    "PlatformAdmin", "BranchManager", "SalesRep", "Dispatcher",
    "Contractor", "CreditAnalyst", "ClaimsAdjuster", "WarehouseClerk",
]


class Caller:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


def get_caller() -> Caller:
    """Priority 1: X-User-ID and X-User-Role must be present and non-empty."""
    user_id = (request.headers.get("X-User-ID") or "").strip()
    role = (request.headers.get("X-User-Role") or "").strip()
    if not user_id or not role:
        raise_error(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers must both be present and non-empty",
        )
    return Caller(user_id, role)


def require_roles(caller: Caller, allowed_roles):
    """Priority 2: endpoint RBAC admission set."""
    if caller.role not in allowed_roles:
        raise_error(ERR_FORBIDDEN,
                    f"role {caller.role} is not authorized for this endpoint")


def authorized(allowed_roles) -> Caller:
    caller = get_caller()
    require_roles(caller, allowed_roles)
    return caller


def check_contractor_owns(caller: Caller, contractor_account_id):
    """Contractor identity is entity-backed: X-User-ID is the ContractorAccount
    id (PRD 2.1). Acting on another contractor's resource is ERR_FORBIDDEN.
    Non-Contractor roles are opaque and never ownership-checked."""
    if caller.role != "Contractor":
        return
    if contractor_account_id is None or caller.user_id != contractor_account_id:
        raise_error(ERR_FORBIDDEN,
                    "contractor may only act on its own resources")
