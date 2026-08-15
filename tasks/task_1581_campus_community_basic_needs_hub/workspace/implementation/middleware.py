"""Auth header extraction, role checks, and entity-backed scoping (PRD 2.1, 2.6)."""
from flask import request

from db import db
from errors import (
    raise_error,
    ERR_UNAUTHENTICATED,
    ERR_FORBIDDEN_ROLE,
    ERR_FORBIDDEN_OWNERSHIP,
    ERR_CONFIDENTIAL,
)

ALL_ROLES = {
    "Anonymous", "Client", "IntakeCoordinator", "PantryStaff", "BenefitsCounselor",
    "GrantReviewer", "ShelterCoordinator", "HubAdmin", "PartnerAgencyRep",
}

STAFF_ROLE_MAP = {
    "IntakeCoordinator": "INTAKE_COORDINATOR",
    "PantryStaff": "PANTRY_STAFF",
    "BenefitsCounselor": "BENEFITS_COUNSELOR",
    "GrantReviewer": "GRANT_REVIEWER",
    "ShelterCoordinator": "SHELTER_COORDINATOR",
}

# Roles walled off from the confidential collections (PRD 2.9)
WALLED_ROLES = {"PantryStaff", "ShelterCoordinator", "PartnerAgencyRep"}


class Caller:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate() -> Caller:
    """Priority 1: header presence + entity-backed identity resolution."""
    role = (request.headers.get("X-User-Role") or "").strip()
    user_id = (request.headers.get("X-User-ID") or "").strip()
    if not role or role not in ALL_ROLES:
        raise_error(ERR_UNAUTHENTICATED, "missing or unknown X-User-Role")
    if role == "Anonymous":
        # X-User-ID may be omitted; when present it is opaque.
        return Caller(user_id or None, role)
    if not user_id:
        raise_error(ERR_UNAUTHENTICATED, "X-User-ID is required for this role")
    if role == "HubAdmin":
        # Opaque operator identity; never resolved against a StaffMember row.
        return Caller(user_id, role)
    if role == "Client":
        c = db["clients"].get(user_id)
        if c is None or c["status"] == "EXITED":
            raise_error(ERR_UNAUTHENTICATED, "X-User-ID is not an existing non-EXITED client")
        return Caller(user_id, role)
    if role in STAFF_ROLE_MAP:
        s = db["staff"].get(user_id)
        if s is None or s["status"] != "ACTIVE" or s["staff_role"] != STAFF_ROLE_MAP[role]:
            raise_error(ERR_UNAUTHENTICATED,
                        "X-User-ID is not an ACTIVE staff member whose staff_role matches the claim")
        return Caller(user_id, role)
    if role == "PartnerAgencyRep":
        a = db["partner_agencies"].get(user_id)
        if a is None:
            raise_error(ERR_UNAUTHENTICATED, "X-User-ID is not an existing partner agency")
        return Caller(user_id, role)
    raise_error(ERR_UNAUTHENTICATED, "unresolvable identity")


def authorize(caller: Caller, allowed_roles, confidential=False):
    """Priority 2: role membership in the endpoint's role list.

    For confidential collections the walled roles pass this step and are then
    rejected at priority 5 with ERR_CONFIDENTIAL (PRD 2.9).
    """
    effective = list(allowed_roles)
    if confidential:
        effective = effective + [r for r in WALLED_ROLES if r not in effective]
    if caller.role not in effective:
        raise_error(ERR_FORBIDDEN_ROLE, f"role {caller.role} is not authorized for this endpoint")


def check_confidential_wall(caller: Caller):
    """Priority 5: walled roles never read assessment or screening data."""
    if caller.role in WALLED_ROLES:
        raise_error(ERR_CONFIDENTIAL, "this role never reads confidential intake data")


def check_client_scope(caller: Caller, client_id):
    """Priority 4: a Client-role caller may only touch its own records."""
    if caller.role == "Client" and caller.user_id != client_id:
        raise_error(ERR_FORBIDDEN_OWNERSHIP, "clients may only touch their own records")


def check_agency_scope(caller: Caller, agency_id):
    """Priority 4: a PartnerAgencyRep may only touch its own agency's referrals."""
    if caller.role == "PartnerAgencyRep" and caller.user_id != agency_id:
        raise_error(ERR_FORBIDDEN_OWNERSHIP, "representatives may only touch their own agency's referrals")


def check_actor_pin(caller: Caller, recorded_actor):
    """Priority 4: action endpoints pinned to a recorded actor require that actor."""
    if recorded_actor is None or caller.user_id != recorded_actor:
        raise_error(ERR_FORBIDDEN_OWNERSHIP, "action is pinned to the recorded actor")
