"""Auth header extraction and role checks (PRD 2.1, validation ladder rungs 1-2)."""
from flask import request

from errors import (
    raise_error,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_FORBIDDEN_ROLE,
)

ALL_ROLES = {
    "UnitAdmin",
    "SchedulingCoordinator",
    "Endoscopist",
    "AnesthesiaProvider",
    "ReprocessingTechnician",
    "InfectionControlNurse",
    "PathologyStaff",
    "QualityOfficer",
}

# Roles permitted on every plain GET list/detail endpoint ("All roles").
ALL_READ_ROLES = sorted(ALL_ROLES)


class Caller:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


def get_caller() -> Caller:
    """Rung 1: X-User-ID and X-User-Role headers present and non-empty."""
    user_id = request.headers.get("X-User-ID", "").strip()
    role = request.headers.get("X-User-Role", "").strip()
    if not user_id or not role:
        raise_error(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers must both be present and non-empty",
        )
    return Caller(user_id, role)


def check_role_allowed(caller: Caller, allowed_roles):
    """Rung 2: the caller's role must be listed for the endpoint."""
    if caller.role not in allowed_roles:
        raise_error(
            ERR_FORBIDDEN_ROLE,
            f"role {caller.role} is not authorized for this endpoint",
        )


def authorized(allowed_roles) -> Caller:
    caller = get_caller()
    check_role_allowed(caller, allowed_roles)
    return caller
