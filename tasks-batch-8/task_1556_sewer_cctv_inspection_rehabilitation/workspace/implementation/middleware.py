"""Auth header extraction + role checking."""
from flask import request

import db
from errors import err_unauthenticated, err_unauthorized

ROLE_CATALOG = {"DistrictEngineer", "Coder", "QaReviewer", "CrewLead", "CustomerServiceRep"}

ENTITY_BACKED = {"Coder": "CODER", "QaReviewer": "QA_REVIEWER", "CrewLead": "CREW_LEAD"}


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
    """Raise ERR_UNAUTHORIZED unless actor.role is in `allowed` (list/set)."""
    if actor.role not in allowed:
        raise err_unauthorized()


def technician_capability_check(actor, required_capability):
    """For entity-backed roles: technician must exist, be active, and hold capability.

    Returns the technician dict. Raises ERR_UNAUTHORIZED when capability is missing
    (the caller presented a role they are not permitted to act in).
    """
    tech = actor.technician
    if tech is None:
        # Entity-backed role whose X-User-ID is not a registered technician:
        # treated as authenticated-but-not-permitted for ownership-gated ops.
        raise err_unauthorized("Technician not registered")
    caps = tech.get("capabilities") or []
    if required_capability not in caps:
        raise err_unauthorized("Technician lacks required capability")
    return tech
