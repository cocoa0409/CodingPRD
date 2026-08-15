"""Auth header extraction and role checks (PRD §2.1, validation priorities 1-2)."""
from flask import request

from errors import (
    raise_error,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_FORBIDDEN_FOR_ROLE,
)

ALL_ROLES = {
    "MobilityAdmin",
    "BusinessUnitApprover",
    "MobilityApprover",
    "PayrollSpecialist",
    "FinanceController",
    "VendorCoordinator",
    "TaxVendor",
    "Assignee",
}

# Read endpoints are open to "Any" — every authenticated role may read.
ANY_ROLES = sorted(ALL_ROLES)


class Caller:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


def get_caller() -> Caller:
    """Priority 1: both headers present and non-empty."""
    user_id = request.headers.get("X-User-ID", "").strip()
    role = request.headers.get("X-User-Role", "").strip()
    if not user_id or not role:
        raise_error(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers must both be present and non-empty",
        )
    return Caller(user_id, role)


def check_role_allowed(caller: Caller, allowed_roles):
    """Priority 2: role membership in the endpoint's declared role list."""
    if caller.role not in allowed_roles:
        raise_error(
            ERR_FORBIDDEN_FOR_ROLE,
            f"role {caller.role} is not authorized for this endpoint",
        )


def authorized(allowed_roles) -> Caller:
    """Run auth priorities 1-2 for a request."""
    caller = get_caller()
    check_role_allowed(caller, allowed_roles)
    return caller
