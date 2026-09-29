"""Identity and authorization — ladder rungs 1, 2 and 6 (PRD §2.1, §2.9)."""

import functools

from flask import g, request

from db import db
from errors import ApiError

PROGRAM_ADMIN = "ProgramAdmin"
PURCHASING_OFFICER = "PurchasingOfficer"
BODY_ENGINEER = "BodyEngineer"
THIRD_PARTY_TESTER = "ThirdPartyTester"
COMMITTEE_REP = "CustomerCommitteeRep"

ALL_ROLES = (
    PROGRAM_ADMIN,
    PURCHASING_OFFICER,
    BODY_ENGINEER,
    THIRD_PARTY_TESTER,
    COMMITTEE_REP,
)


def authorize(*allowed_roles):
    """Rung 1 then rung 2: identity present and role declared, then permitted."""

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not role or role not in ALL_ROLES:
                raise ApiError("ERR_MISSING_AUTH_HEADERS")
            if role not in allowed_roles:
                raise ApiError("ERR_ROLE_NOT_PERMITTED")
            g.user_id = user_id
            g.role = role
            return view(*args, **kwargs)

        return wrapper

    return decorator


def acting_user_id():
    return g.user_id


def acting_role():
    return g.role


def committee_scope_check(program_id):
    """Rung 6. A `CustomerCommitteeRep`'s X-User-ID *is* its ApparatusProgram id."""
    if g.role != COMMITTEE_REP:
        return
    if program_id is None or g.user_id != program_id:
        raise ApiError("ERR_COMMITTEE_SCOPE_VIOLATION")


def committee_scope_for_unit(unit):
    committee_scope_check(unit["program_id"] if unit else None)


def committee_scope_for_trip(trip):
    unit = db.unit_orders.get(trip["unit_order_id"]) if trip else None
    committee_scope_for_unit(unit)


def committee_scope_for_change_order(change_order):
    unit = db.unit_orders.get(change_order["unit_order_id"]) if change_order else None
    committee_scope_for_unit(unit)
