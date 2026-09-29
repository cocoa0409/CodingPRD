"""Authentication, RBAC and entity-backed identity resolution (PRD 2.1, 2.11)."""

from flask import g, request

import config
import db
from errors import ApiError


def authenticate():
    """Gauntlet position 1: both identity headers must be present and well formed."""
    user_id = request.headers.get(config.HEADER_USER_ID)
    role = request.headers.get(config.HEADER_USER_ROLE)
    if user_id is None or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    if role is None or not str(role).strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    g.user_id = user_id
    g.user_role = role
    return user_id, role


def authorize(allowed_roles, clinician_identity=False):
    """Positions 1-3 of the gauntlet, in order."""
    user_id, role = authenticate()

    # Position 2: the role must be a declared role and permitted on this operation.
    if role not in config.ALL_ROLES or role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")

    # Position 3: entity-backed identities must resolve to a Doctor row.
    doctor = None
    if role in config.ENTITY_BACKED_ROLES:
        doctor = db.get("doctors", user_id)
        if clinician_identity and doctor is None:
            raise ApiError("ERR_UNAUTHORIZED")
    g.actor_doctor = doctor
    return user_id, role
