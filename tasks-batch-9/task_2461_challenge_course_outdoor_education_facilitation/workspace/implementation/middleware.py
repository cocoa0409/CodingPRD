"""Auth header extraction, role authorisation and entity-backed identity
resolution (PRD 2.1, order-of-rejection steps 1-3)."""
from flask import request, g

from db import store
from errors import ApiError

ROLES = (
    "ProgramDirector",
    "SafetyOfficer",
    "Facilitator",
    "ProfessionalInspector",
    "GroupCoordinator",
)

ALL_ROLES = ROLES


def authorize(allowed_roles, identity=True):
    """Steps 1-3 of PRD 2.12.

    ``identity=False`` is used only by course registration and the clock
    endpoint, both reachable before any staff record exists.
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")

    if not role or not user_id or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")

    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")

    actor = None
    if identity:
        actor = _resolve_identity(role, user_id)

    g.role = role
    g.user_id = user_id
    g.actor = actor
    return role, user_id, actor


def _resolve_identity(role, user_id):
    if role == "ProgramDirector":
        # Opaque operator identifier; never compared to a row id.
        return None

    if role == "GroupCoordinator":
        client = store.group_clients.get(user_id)
        if client is None:
            raise ApiError("ERR_ROLE_IDENTITY_MISMATCH")
        return client

    facilitator = store.facilitators.get(user_id)
    if facilitator is None:
        raise ApiError("ERR_ROLE_IDENTITY_MISMATCH")

    if role == "Facilitator":
        if facilitator["staff_type"] != "STAFF_FACILITATOR":
            raise ApiError("ERR_ROLE_IDENTITY_MISMATCH")
    elif role == "ProfessionalInspector":
        if facilitator["staff_type"] != "CONTRACT_INSPECTOR" or facilitator["is_operator_employee"]:
            raise ApiError("ERR_ROLE_IDENTITY_MISMATCH")
    elif role == "SafetyOfficer":
        if facilitator["staff_type"] != "SAFETY_OFFICER" or facilitator["certification_level"] != "LEVEL_3":
            raise ApiError("ERR_ROLE_IDENTITY_MISMATCH")
    return facilitator
