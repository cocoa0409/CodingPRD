"""Auth header extraction and role checks (PRD 2.1, validation priorities 1-2).

Every request carries X-User-ID (opaque operator id) and X-User-Role (one of the
four roles). Missing/empty headers -> ERR_MISSING_OR_INVALID_USER_CONTEXT (400).
A role not permitted on the endpoint -> ERR_FORBIDDEN_FOR_ROLE (403).
All four roles use opaque identifiers; the server records but never resolves them.
"""
from flask import request

from errors import (
    raise_error,
    ERR_MISSING_OR_INVALID_USER_CONTEXT,
    ERR_FORBIDDEN_FOR_ROLE,
)

ROLE_OPS_ADMIN = "OpsAdmin"
ROLE_INTAKE = "IntakeCoordinator"
ROLE_RT = "RespiratoryTherapist"
ROLE_BILLING = "BillingSpecialist"

ALL_ROLES = [ROLE_OPS_ADMIN, ROLE_INTAKE, ROLE_RT, ROLE_BILLING]


class Caller:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


def get_caller() -> Caller:
    """Priority 1: header presence / well-formedness."""
    user_id = request.headers.get("X-User-ID", "")
    role = request.headers.get("X-User-Role", "")
    user_id = user_id.strip() if isinstance(user_id, str) else ""
    role = role.strip() if isinstance(role, str) else ""
    if not user_id or not role:
        raise_error(
            ERR_MISSING_OR_INVALID_USER_CONTEXT,
            "X-User-ID and X-User-Role headers must both be present and well-formed",
        )
    return Caller(user_id, role)


def authorized(allowed_roles) -> Caller:
    """Priority 1 (headers) then priority 2 (role permitted on this endpoint)."""
    caller = get_caller()
    if caller.role not in allowed_roles:
        raise_error(
            ERR_FORBIDDEN_FOR_ROLE,
            f"role {caller.role} is not permitted for this endpoint",
        )
    return caller
