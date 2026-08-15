"""Auth header extraction and role checks (PRD 2.1; validation pipeline stages 1-2)."""
from flask import request

from errors import (
    raise_error,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_INSUFFICIENT_PERMISSIONS,
)

ALL_ROLES = ("PlanAdmin", "MedicalPolicyOfficer", "ProviderRep", "CaseManager", "PharmacyAnalyst")


class Caller:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


def get_caller() -> Caller:
    """Pipeline stage 1: both headers present and the role is a declared role."""
    user_id = (request.headers.get("X-User-ID") or "").strip()
    role = (request.headers.get("X-User-Role") or "").strip()
    if not user_id or not role or role not in ALL_ROLES:
        raise_error(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers must be present and name a declared role",
        )
    return Caller(user_id, role)


def authorized(allowed_roles) -> Caller:
    """Pipeline stages 1-2: header context, then role permission for the endpoint."""
    caller = get_caller()
    if caller.role not in allowed_roles:
        raise_error(
            ERR_INSUFFICIENT_PERMISSIONS,
            f"role {caller.role} is not permitted for this endpoint",
        )
    return caller
