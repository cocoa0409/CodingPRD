"""Auth header extraction and role checks (PRD 2.1; validation priorities 1-2)."""
from flask import request

from errors import (
    raise_error,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_FORBIDDEN_FOR_ROLE,
)

ALL_ROLES = [
    "DealerAdmin",
    "AccountExecutive",
    "ContractsOfficer",
    "Designer",
    "ClientApprover",
    "ProjectManager",
    "WarehouseLead",
    "ClaimsCoordinator",
    "ManufacturerRep",
    "LiquidationAppraiser",
    "FinanceManager",
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
    """Priority 2: caller role must be listed for the endpoint."""
    if caller.role not in allowed_roles:
        raise_error(
            ERR_FORBIDDEN_FOR_ROLE,
            f"role {caller.role} is not authorized for this endpoint",
        )
