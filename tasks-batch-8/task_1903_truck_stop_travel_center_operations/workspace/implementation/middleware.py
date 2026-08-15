"""Auth headers, role checks, entity-backed scoping, segregation of duties
(SCAFFOLD validations priorities 1-4; PRD 2.1)."""
from flask import request

from errors import (
    raise_error,
    ERR_UNAUTHENTICATED,
    ERR_FORBIDDEN,
    ERR_SEGREGATION_OF_DUTIES,
)

ALL_ROLES = [
    "GeneralManager",
    "ShiftManager",
    "FuelDeskLead",
    "Cashier",
    "MaintenanceTech",
    "FleetManager",
    "LoyaltyMember",
]
ALL_ROLES_SET = set(ALL_ROLES)


class Caller:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


def get_caller() -> Caller:
    """Priority 1: X-User-Role and X-User-ID present; role one of the declared set."""
    user_id = (request.headers.get("X-User-ID") or "").strip()
    role = (request.headers.get("X-User-Role") or "").strip()
    if not user_id or not role or role not in ALL_ROLES_SET:
        raise_error(ERR_UNAUTHENTICATED,
                    "X-User-ID and X-User-Role headers must be present and role must be declared")
    return Caller(user_id, role)


def authorized(allowed_roles) -> Caller:
    """Priorities 1-2: header presence then endpoint role membership."""
    caller = get_caller()
    if caller.role not in allowed_roles:
        raise_error(ERR_FORBIDDEN,
                    f"role {caller.role} is not authorized for this endpoint")
    return caller


# ---------------------------------------------------------------------------
# Priority 3: entity-backed identity scoping (PRD 2.1)
# ---------------------------------------------------------------------------

def scope_member(caller: Caller, member_id):
    """LoyaltyMember may only touch resources whose loyalty_member_id == X-User-ID."""
    if caller.role == "LoyaltyMember" and caller.user_id != member_id:
        raise_error(ERR_FORBIDDEN, "member may only access its own resources")


def scope_fleet(caller: Caller, fleet_account_id):
    """FleetManager may only touch its own FleetAccount subtree."""
    if caller.role == "FleetManager" and caller.user_id != fleet_account_id:
        raise_error(ERR_FORBIDDEN, "fleet manager may only access its own fleet subtree")


def scope_technician(caller: Caller, technician_id):
    """MaintenanceTech start-work/parts only on work orders assigned to X-User-ID."""
    if caller.role == "MaintenanceTech" and caller.user_id != technician_id:
        raise_error(ERR_FORBIDDEN, "technician may only operate work orders assigned to them")


def scope_cashier_shift(caller: Caller, shift):
    """Cashier may record a drop only on a shift whose cashier_user_id == X-User-ID."""
    if caller.role == "Cashier" and shift is not None and shift.get("cashier_user_id") != caller.user_id:
        raise_error(ERR_FORBIDDEN, "cashier may only record drops on their own shift")


def check_segregation(caller: Caller, other_user_id, what="operation"):
    """Priority 4: segregation of duties — actor must differ from the other principal."""
    if other_user_id is not None and caller.user_id == other_user_id:
        raise_error(ERR_SEGREGATION_OF_DUTIES,
                    f"segregation of duties violated for {what}")
