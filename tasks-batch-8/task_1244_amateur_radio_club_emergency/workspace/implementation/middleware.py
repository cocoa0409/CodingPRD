"""Auth context extraction and role checks (PRD §2.1, validations priority 1-2)."""
from flask import request

import db
from errors import ERR_FORBIDDEN, ERR_UNAUTHENTICATED, ApiError

DECLARED_ROLES = {
    "ClubAdmin",
    "Member",
    "NetControl",
    "EmergencyCoordinator",
    "ExamLiaison",
}

# Roles whose X-User-ID must reference an existing Member (entity_backed).
ENTITY_BACKED_ROLES = {"Member", "NetControl", "EmergencyCoordinator", "ExamLiaison"}


def auth_context():
    """Validate X-User-ID / X-User-Role headers. Returns (user_id, role).

    ERR_UNAUTHENTICATED when either header is missing, the role is outside the
    declared set, or an entity-backed role's X-User-ID names no existing Member.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in DECLARED_ROLES:
        raise ApiError(
            ERR_UNAUTHENTICATED, 401,
            "X-User-ID and X-User-Role headers are required and role must be declared",
        )
    if role in ENTITY_BACKED_ROLES and user_id not in db.STORE["members"]:
        raise ApiError(
            ERR_UNAUTHENTICATED, 401,
            "X-User-ID does not reference an existing Member",
        )
    return user_id, role


def require_role(role, allowed):
    """allowed is a collection of role names permitted on the endpoint."""
    if role not in allowed:
        raise ApiError(
            ERR_FORBIDDEN, 403,
            "role %s is not permitted for this endpoint" % role,
        )
