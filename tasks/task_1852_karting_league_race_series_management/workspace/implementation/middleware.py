"""Auth header extraction, role checks, driver ownership (PRD 2.1).

Headers: X-User-ID (required) and X-User-Role (must be one of the four
declared roles). For the Driver role, X-User-ID is the id of the acting
Driver resource; for LeagueAdmin / RaceDirector / Steward it is an opaque
operator identifier never compared to any entity id.
"""
from flask import request

from errors import (
    raise_error,
    ERR_UNAUTHENTICATED,
    ERR_FORBIDDEN,
)

ROLES = {"LeagueAdmin", "RaceDirector", "Steward", "Driver"}
ANY_ROLE = ["LeagueAdmin", "RaceDirector", "Steward", "Driver"]


class Caller:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


def get_caller() -> Caller:
    """Validation priority 1: headers present and role recognized."""
    user_id = request.headers.get("X-User-ID", "").strip()
    role = request.headers.get("X-User-Role", "").strip()
    if not user_id or role not in ROLES:
        raise_error(
            ERR_UNAUTHENTICATED,
            "X-User-ID and X-User-Role headers are required and the role must be recognized",
        )
    return Caller(user_id, role)


def require_roles(caller: Caller, allowed_roles):
    """Validation priority 2: role permitted for the endpoint."""
    if caller.role not in allowed_roles:
        raise_error(
            ERR_FORBIDDEN,
            f"role {caller.role} is not permitted for this endpoint",
        )


def authorized(allowed_roles) -> Caller:
    caller = get_caller()
    require_roles(caller, allowed_roles)
    return caller


def check_driver_ownership(caller: Caller, owner_driver_id):
    """Priority 2 driver-ownership rule: a Driver may perform driver-scoped
    mutations only on resources whose driver_id equals their X-User-ID.
    LeagueAdmin is exempt where the endpoint allows the role at all."""
    if caller.role == "Driver" and owner_driver_id is not None:
        if caller.user_id != owner_driver_id:
            raise_error(
                ERR_FORBIDDEN,
                "driver-scoped mutation attempted by a non-owner",
            )
