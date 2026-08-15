"""Auth header extraction and role checks (PRD 2.1, validation order steps 1-2)."""
from flask import request

from errors import raise_error, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ALL_ROLES = {
    "PublicUser",
    "Claimant",
    "IntakeOfficer",
    "PropertyCustodian",
    "ClaimsExaminer",
    "ReleaseOfficer",
    "PoliceLiaison",
    "AuctionCoordinator",
    "ProgramAdmin",
}

STAFF_ROLES = {
    "IntakeOfficer",
    "PropertyCustodian",
    "ClaimsExaminer",
    "ReleaseOfficer",
    "PoliceLiaison",
    "AuctionCoordinator",
    "ProgramAdmin",
}


class Caller:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


def get_caller() -> Caller:
    """Step 1: X-User-Role must name a declared role; X-User-ID required for all
    roles except PublicUser."""
    role = (request.headers.get("X-User-Role") or "").strip()
    user_id = (request.headers.get("X-User-ID") or "").strip()
    if not role or role not in ALL_ROLES:
        raise_error(ERR_UNAUTHENTICATED, "missing or unrecognized X-User-Role header")
    if role != "PublicUser" and not user_id:
        raise_error(ERR_UNAUTHENTICATED, "X-User-ID header is required for this role")
    return Caller(user_id, role)


def require_roles(caller: Caller, allowed_roles):
    """Step 2: role membership in the endpoint's declared role list."""
    if caller.role not in allowed_roles:
        raise_error(
            ERR_FORBIDDEN,
            f"role {caller.role} is not authorized for this endpoint",
        )


def authorized(allowed_roles) -> Caller:
    caller = get_caller()
    require_roles(caller, allowed_roles)
    return caller
