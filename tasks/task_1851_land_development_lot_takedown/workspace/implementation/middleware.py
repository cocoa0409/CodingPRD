"""Auth header extraction, role checks, entity-backed ownership (PRD 2.1).

Headers: X-User-ID (required) and X-User-Role (must name a declared role).
Entity-backed roles:
  - BuilderRep: X-User-ID is a Builder id; ownership compares an agreement's
    builder_id to X-User-ID.
  - HOAManager: X-User-ID is an HOAAssociation id; ownership compares the
    association's own id to X-User-ID.
DeveloperOperator / LenderOfficer / MunicipalClerk are opaque identifiers.
"""
from flask import request

from errors import raise_error, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE

DECLARED_ROLES = {
    "DeveloperOperator",
    "BuilderRep",
    "LenderOfficer",
    "MunicipalClerk",
    "HOAManager",
}

ALL_ROLES = ["DeveloperOperator", "BuilderRep", "LenderOfficer", "MunicipalClerk", "HOAManager"]


class Caller:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


def get_caller() -> Caller:
    """Priority 1: header presence and declared role."""
    user_id = request.headers.get("X-User-ID", "").strip()
    role = request.headers.get("X-User-Role", "").strip()
    if not user_id or role not in DECLARED_ROLES:
        raise_error(ERR_UNAUTHENTICATED,
                    "X-User-ID must be present and X-User-Role must name a declared role")
    return Caller(user_id, role)


def check_role(caller: Caller, allowed_roles):
    """Priority 2: role membership in the endpoint's declared role list."""
    if caller.role not in allowed_roles:
        raise_error(ERR_FORBIDDEN_ROLE,
                    f"role {caller.role} is not authorized for this endpoint")


def authorized(allowed_roles) -> Caller:
    caller = get_caller()
    check_role(caller, allowed_roles)
    return caller


def check_builder_ownership(caller: Caller, agreement):
    """Priority 2 (entity-backed): a BuilderRep may act only under agreements
    whose builder_id equals the caller's X-User-ID. Only evaluated when the
    agreement resolves; an unresolvable reference falls through to the
    priority-3 existence check."""
    if caller.role == "BuilderRep" and agreement is not None:
        if agreement.get("builder_id") != caller.user_id:
            raise_error(ERR_FORBIDDEN_ROLE,
                        "BuilderRep may only act on their own builder's agreements")


def check_hoa_ownership(caller: Caller, association):
    """Priority 2 (entity-backed): an HOAManager may act only on the
    association whose id equals the caller's X-User-ID."""
    if caller.role == "HOAManager" and association is not None:
        if association.get("id") != caller.user_id:
            raise_error(ERR_FORBIDDEN_ROLE,
                        "HOAManager may only act on their own association")
