"""Auth context, role checks, and entity-backed ownership scope.

Pipeline priorities 1-3 from SCAFFOLD.yaml §1.4:
  1. X-User-ID / X-User-Role present and role declared
     -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400)
  2. Caller role in endpoint roles -> ERR_FORBIDDEN_FOR_ROLE (403)
  3. Entity-backed ownership (DistrictBuyer == District.id, CrewLead == Crew.id)
     -> ERR_SCOPE_VIOLATION (403)
"""
from flask import request

from errors import (
    ERR_FORBIDDEN_FOR_ROLE,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_SCOPE_VIOLATION,
    raise_err,
)

ROLES = {
    "ContractorAdmin",
    "ContractManager",
    "FulfillmentCoordinator",
    "CrewLead",
    "DistrictBuyer",
    "ServiceAgent",
}

ALL_ROLES = [
    "ContractorAdmin",
    "ContractManager",
    "FulfillmentCoordinator",
    "ServiceAgent",
    "CrewLead",
    "DistrictBuyer",
]


class Caller:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """Priority 1: user context headers present and role declared."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise_err(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers are required and X-User-Role must be a declared role",
        )
    return Caller(user_id, role)


def require_roles(caller, allowed):
    """Priority 2: caller role must be listed in the endpoint's roles."""
    if caller.role not in allowed:
        raise_err(ERR_FORBIDDEN_FOR_ROLE, f"Role {caller.role} is not authorized for this endpoint")


def scope_district(caller, district_id):
    """Priority 3: DistrictBuyer may only act within their own district chain."""
    if caller.role == "DistrictBuyer" and district_id is not None and caller.user_id != district_id:
        raise_err(ERR_SCOPE_VIOLATION, "DistrictBuyer may only act on resources of their own district")


def scope_crew(caller, crew_id):
    """Priority 3: CrewLead may only act on their own crew's tasks."""
    if caller.role == "CrewLead" and crew_id is not None and caller.user_id != crew_id:
        raise_err(ERR_SCOPE_VIOLATION, "CrewLead may only act on their own crew's tasks")
