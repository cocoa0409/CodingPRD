"""Auth header extraction and role/ownership checks (PRD 2.1, validations 1-4)."""
from flask import request

from errors import (
    raise_error,
    ERR_UNAUTHENTICATED,
    ERR_FORBIDDEN,
    ERR_OWNERSHIP_VIOLATION,
)

ALL_ROLES = {
    "Patient",
    "FinancialCounselor",
    "AssistanceReviewer",
    "BillingAdministrator",
    "CollectionsAgent",
    "ComplianceOfficer",
}

STAFF_ROLES = ALL_ROLES - {"Patient"}


class Caller:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


def get_caller() -> Caller:
    """Priority 1: X-User-ID and X-User-Role present and role is declared."""
    user_id = request.headers.get("X-User-ID", "").strip()
    role = request.headers.get("X-User-Role", "").strip()
    if not user_id or not role or role not in ALL_ROLES:
        raise_error(
            ERR_UNAUTHENTICATED,
            "X-User-ID and X-User-Role headers must be present and role must be a declared role",
        )
    return Caller(user_id, role)


def authorized(allowed_roles) -> Caller:
    """Priorities 1-2: header presence, then role permitted for this endpoint."""
    caller = get_caller()
    if caller.role not in allowed_roles:
        raise_error(
            ERR_FORBIDDEN,
            f"role {caller.role} is not permitted for this endpoint",
        )
    return caller


def check_ownership(caller: Caller, patient_id):
    """Priority 4: a Patient caller may only act on resources of their own patient_id.

    Staff roles are exempt; patient_id=None means the target chain cannot be
    resolved (never deny staff, and a Patient caller fails only on mismatch)."""
    if caller.role != "Patient":
        return
    if patient_id is None or caller.user_id != patient_id:
        raise_error(
            ERR_OWNERSHIP_VIOLATION,
            "patient callers may only access resources of their own patient_id",
        )
