"""Auth header extraction + role checking."""
from flask import request

import db
from errors import err_unauthenticated, err_forbidden_role

ROLE_CATALOG = {
    "OperationsManager",
    "OutageCoordinator",
    "SwitchingSupervisor",
    "Technician",
    "ComplianceOfficer",
}

ALL_ROLES = sorted(ROLE_CATALOG)

# Entity-backed roles: X-User-ID is the id of a Technician entity.
ENTITY_BACKED = {"Technician"}


class Actor:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_entity_backed(self):
        return self.role in ENTITY_BACKED

    @property
    def technician(self):
        if not self.is_entity_backed:
            return None
        return db.technicians.get(self.user_id)


def get_actor():
    """Authenticate the request. Returns Actor or raises ERR_UNAUTHENTICATED."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id:
        raise err_unauthenticated()
    if role not in ROLE_CATALOG:
        raise err_unauthenticated()
    return Actor(user_id, role)


def require_roles(actor, allowed):
    """Raise ERR_FORBIDDEN_ROLE unless actor.role is in `allowed` (list/set)."""
    if actor.role not in allowed:
        raise err_forbidden_role()
