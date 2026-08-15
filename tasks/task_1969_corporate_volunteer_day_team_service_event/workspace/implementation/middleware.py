"""Auth header extraction and role checks (PRD 2.1, validation pipeline steps 1-3)."""
from flask import request

from db import db
from errors import (
    raise_err,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_FORBIDDEN_ROLE,
    ERR_VOLUNTEER_NOT_FOUND,
)

ROLES = {
    "CommunityEngagementManager",
    "NonprofitCoordinator",
    "EmployeeVolunteer",
    "StaffLead",
    "ProcurementOfficer",
    "LogisticsCoordinator",
    "FinanceController",
    "PlatformAdmin",
    "Any",
}

ENTITY_BACKED_VOLUNTEER_ROLES = {"EmployeeVolunteer", "StaffLead"}


def get_auth():
    """Pipeline step 1: header context. Returns (user_id, role)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise_err(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers are required and role must be recognized",
        )
    return uid, role


def require_roles(role, allowed):
    """Pipeline step 2 (role authorization). `allowed` is a list of role names; 'Any' open to all."""
    if "Any" in allowed:
        return
    if role not in allowed:
        raise_err(ERR_FORBIDDEN_ROLE, f"role {role} is not authorized for this endpoint")


def resolve_identity(role, uid):
    """Pipeline step 2 (entity-backed identity): EmployeeVolunteer/StaffLead X-User-ID must be
    an existing EmployeeVolunteer. Returns the volunteer record or None for opaque roles."""
    if role in ENTITY_BACKED_VOLUNTEER_ROLES:
        vol = db.volunteers.get(uid)
        if vol is None:
            raise_err(ERR_VOLUNTEER_NOT_FOUND, "X-User-ID does not correspond to an existing volunteer")
        return vol
    return None


def authenticate(allowed_roles):
    """Combined steps 1-2: headers -> role authorization -> entity identity resolution.

    Returns (uid, role, volunteer_or_none)."""
    uid, role = get_auth()
    require_roles(role, allowed_roles)
    vol = resolve_identity(role, uid)
    return uid, role, vol


def body():
    """Parse JSON body tolerantly; absent/non-JSON bodies become {}."""
    return request.get_json(silent=True) or {}
