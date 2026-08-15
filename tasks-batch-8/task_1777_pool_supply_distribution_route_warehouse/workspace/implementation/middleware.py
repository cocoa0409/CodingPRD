"""Auth header extraction and role checks (PRD 2.1, validation priorities 1-3)."""
from flask import request

from errors import (
    raise_error,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_NOT_RESOURCE_OWNER,
    ERR_NOT_CLAIM_OWNER,
)

ALL_ROLES = {"BranchManager", "CounterRep", "RouteDispatcher", "WarehouseLead", "Account"}


class Caller:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


def get_caller() -> Caller:
    """Priority 1: X-User-ID and X-User-Role present, role declared."""
    user_id = request.headers.get("X-User-ID", "").strip()
    role = request.headers.get("X-User-Role", "").strip()
    if not user_id or not role or role not in ALL_ROLES:
        raise_error(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers must be present and role must be declared",
        )
    return Caller(user_id, role)


def require_roles(caller: Caller, allowed_roles):
    """Priority 2: role permitted for this endpoint."""
    if caller.role not in allowed_roles:
        raise_error(
            ERR_INSUFFICIENT_PERMISSIONS,
            f"role {caller.role} is not permitted for this endpoint",
        )


def check_account_ownership(caller: Caller, account_id):
    """Priority 3: Account role may only act on resources whose account_id == X-User-ID."""
    if caller.role == "Account" and caller.user_id != account_id:
        raise_error(
            ERR_NOT_RESOURCE_OWNER,
            "Account principal may only act on its own resources",
        )


def check_claim_ownership(caller: Caller, claim):
    """Claim supply-info ownership uses the claim-specific error id (PRD 3.8)."""
    if caller.role == "Account" and caller.user_id != claim["account_id"]:
        raise_error(ERR_NOT_CLAIM_OWNER, "caller does not own this claim")
