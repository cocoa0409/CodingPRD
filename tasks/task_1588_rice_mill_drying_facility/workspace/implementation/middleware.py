"""Auth header extraction, role authorization, GrowerRep identity scoping (PRD §2.1, §2.7)."""
from flask import request

from errors import (
    raise_error,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_FORBIDDEN_ROLE,
    ERR_IDENTITY_SCOPE_VIOLATION,
)

ALL_ROLES = [
    "MillAdmin", "Merchandiser", "ScaleOperator", "QualityLabTech", "DryerOperator",
    "MillSupervisor", "SettlementClerk", "GrowerRep", "SafetyOfficer", "FumigationTech",
]
ROLE_SET = set(ALL_ROLES)


class Caller:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


def get_caller() -> Caller:
    """Priority 1: X-User-ID / X-User-Role present and role declared."""
    user_id = (request.headers.get("X-User-ID") or "").strip()
    role = (request.headers.get("X-User-Role") or "").strip()
    if not user_id or not role or role not in ROLE_SET:
        raise_error(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                    "X-User-ID and X-User-Role headers are required and role must be a declared role")
    return Caller(user_id, role)


def authorized(allowed_roles) -> Caller:
    """Priorities 1-2: header presence/validity, then role permission."""
    caller = get_caller()
    if caller.role not in allowed_roles:
        raise_error(ERR_FORBIDDEN_ROLE,
                    f"role {caller.role} is not permitted for this endpoint")
    return caller


def check_grower_scope(caller: Caller, grower_id):
    """Priority 3: GrowerRep may only touch resources whose grower_id == X-User-ID.

    Resources without a grower identity (grower_id is None) are not scoped.
    """
    if caller.role != "GrowerRep":
        return
    if grower_id is None:
        return
    if caller.user_id != grower_id:
        raise_error(ERR_IDENTITY_SCOPE_VIOLATION,
                    "GrowerRep may only access records of the grower identified by X-User-ID")


def grower_scope_id(caller: Caller):
    """Return the grower id a GrowerRep list view is restricted to, else None."""
    if caller.role == "GrowerRep":
        return caller.user_id
    return None
