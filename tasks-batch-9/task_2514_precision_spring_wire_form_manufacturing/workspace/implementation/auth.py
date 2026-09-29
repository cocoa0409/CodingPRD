"""Header authentication, role authorisation and customer ownership (PRD 2.1)."""

from flask import request

import store
from errors import ApiError

DESIGN_ENGINEER = "DesignEngineer"
ENGINEERING_MANAGER = "EngineeringManager"
PROCESS_TECHNICIAN = "ProcessTechnician"
QUALITY_INSPECTOR = "QualityInspector"
PROGRAM_MANAGER = "ProgramManager"
CUSTOMER_REPRESENTATIVE = "CustomerRepresentative"
PLANT_ADMIN = "PlantAdmin"

ROLES = (
    DESIGN_ENGINEER,
    ENGINEERING_MANAGER,
    PROCESS_TECHNICIAN,
    QUALITY_INSPECTOR,
    PROGRAM_MANAGER,
    CUSTOMER_REPRESENTATIVE,
    PLANT_ADMIN,
)

ALL_ROLES = ROLES


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_customer(self):
        return self.role == CUSTOMER_REPRESENTATIVE


def guard(*allowed):
    """Authenticate (rank 1) then authorise (rank 2)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role are required.")
    user_id = user_id.strip()
    role = role.strip()
    if not user_id or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Unknown or missing acting role.")
    if allowed and role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED",
                       "Role %s is not authorised for this endpoint." % role)
    return Actor(user_id, role)


def own_program(actor, program_id):
    """Rank 3: a CustomerRepresentative may only touch its own program."""
    if actor.is_customer and actor.user_id != program_id:
        raise ApiError("ERR_PROGRAM_OWNERSHIP_MISMATCH",
                       "This resource belongs to a different customer program.")


def customer_program_filter(actor, requested_program_id):
    """Force list endpoints down to the caller's own program."""
    if not actor.is_customer:
        return requested_program_id
    if requested_program_id is not None and requested_program_id != actor.user_id:
        raise ApiError("ERR_PROGRAM_OWNERSHIP_MISMATCH",
                       "A customer representative may only list its own program's rows.")
    return actor.user_id


def program_of_design(design_id):
    design = store.designs.get(design_id)
    return design["program_id"] if design else None
