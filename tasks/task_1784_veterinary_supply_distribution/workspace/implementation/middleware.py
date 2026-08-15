"""Auth header extraction, role checks, and ClinicBuyer ownership scoping.

PRD §2.1 / §2.8 pipeline order:
  1. X-User-ID and X-User-Role present, role recognized
     -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400)
  2. Role permitted on the endpoint -> ERR_UNAUTHORIZED_ROLE (403)
  3. Ownership: ClinicBuyer mutations only against resources whose clinic_id
     equals X-User-ID -> ERR_FORBIDDEN_OWNERSHIP (403)
"""
from flask import request

from errors import (
    raise_error,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_UNAUTHORIZED_ROLE,
    ERR_FORBIDDEN_OWNERSHIP,
)

ALL_ROLES = {
    "ClinicBuyer",
    "AccountManager",
    "SupplyChainPlanner",
    "ComplianceOfficer",
    "SystemAdmin",
}


class Caller:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


def get_caller() -> Caller:
    """Pipeline step 1: header presence + recognized role."""
    user_id = request.headers.get("X-User-ID", "").strip()
    role = request.headers.get("X-User-Role", "").strip()
    if not user_id or not role or role not in ALL_ROLES:
        raise_error(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers must be present and the role recognized",
        )
    return Caller(user_id, role)


def authorized(allowed_roles) -> Caller:
    """Pipeline steps 1-2."""
    caller = get_caller()
    if caller.role not in allowed_roles:
        raise_error(
            ERR_UNAUTHORIZED_ROLE,
            f"role {caller.role} is not permitted on this endpoint",
        )
    return caller


def check_ownership(caller: Caller, clinic_id):
    """Pipeline step 3: ClinicBuyer may only act on own-clinic resources.

    Other roles are unscoped. Reads are never ownership-scoped.
    """
    if caller.role == "ClinicBuyer":
        if clinic_id is None or str(clinic_id) != caller.user_id:
            raise_error(
                ERR_FORBIDDEN_OWNERSHIP,
                "ClinicBuyer may only act on resources of its own clinic",
            )
