"""Auth header extraction + role checking per PRD 2.1."""
from flask import request

from errors import err_missing_context, err_forbidden_role

ROLE_CATALOG = {
    "FacilityManager",
    "ParkingAttendant",
    "RevenueAuditor",
    "MaintenanceSupervisor",
    "SecurityOfficer",
    "GateDevice",
    "MonthlyParker",
}

ALL_ROLES = [
    "FacilityManager",
    "ParkingAttendant",
    "RevenueAuditor",
    "MaintenanceSupervisor",
    "SecurityOfficer",
    "GateDevice",
    "MonthlyParker",
]


class Actor:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def get_actor():
    """Authenticate the request. Returns Actor or raises ERR_MISSING_CONTEXT_HEADER."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err_missing_context()
    if role not in ROLE_CATALOG:
        raise err_missing_context()
    return Actor(user_id, role)


def require_roles(actor, allowed):
    """Raise ERR_FORBIDDEN_ROLE unless actor.role is in `allowed`."""
    if actor.role not in allowed:
        raise err_forbidden_role()
