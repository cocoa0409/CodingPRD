"""Auth header extraction and role checking."""

from flask import request

from db import store
from errors import (
    ApiError,
    ERR_FORBIDDEN_ROLE,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_NOT_SUPERVISOR_CAPABLE,
)

ROLES = {
    "PropertyAdmin",
    "Dispatcher",
    "OnCallTechnician",
    "MaintenanceSupervisor",
    "Vendor",
}

# Roles that are technician-backed: X-User-ID must be a Technician id.
TECHNICIAN_BACKED = {"OnCallTechnician", "MaintenanceSupervisor"}


class Actor:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_technician_backed(self):
        return self.role in TECHNICIAN_BACKED


def get_actor():
    """Priority 1 auth: headers present and role declared."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers are required and role must be a declared role",
            401,
        )
    return Actor(user_id, role)


def require_role(actor, allowed_roles):
    """Priority 2: role membership for the endpoint."""
    if actor.role not in allowed_roles:
        raise ApiError(
            ERR_FORBIDDEN_ROLE,
            "Role not permitted for this endpoint",
            403,
        )


def require_supervisor_capable(actor):
    """Priority 2: MaintenanceSupervisor requires capability == SUPERVISOR."""
    if actor.role != "MaintenanceSupervisor":
        return
    tech = store.technicians.get(actor.user_id)
    if tech is None or tech.get("capability") != "SUPERVISOR":
        raise ApiError(
            ERR_NOT_SUPERVISOR_CAPABLE,
            "MaintenanceSupervisor role requires a Technician with capability SUPERVISOR",
            403,
        )
