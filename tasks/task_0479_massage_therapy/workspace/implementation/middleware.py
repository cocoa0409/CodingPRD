"""Auth + RBAC (PRD §2.1)."""
from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

ROLES = {"PracticeAdmin", "FrontDesk", "Therapist", "Client"}

# Roles whose identity is tied to a persisted entity (X-User-ID required).
ENTITY_BACKED = {"Therapist", "Client"}


class Caller:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """Validate auth headers. Raise ERR_UNAUTHENTICATED on failure.

    - X-User-Role missing or not one of the four roles -> 401
    - X-User-ID missing for an entity-backed role -> 401
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in ROLES:
        raise ApiError(*ERR_UNAUTHENTICATED, message="Missing or invalid role")
    if role in ENTITY_BACKED and (user_id is None or user_id == ""):
        raise ApiError(*ERR_UNAUTHENTICATED, message="Missing user id")
    return Caller(user_id, role)


def require_role(caller, allowed):
    """Authorization check. Raise ERR_UNAUTHORIZED if role not permitted."""
    if caller.role not in allowed:
        raise ApiError(*ERR_UNAUTHORIZED, message="Role not permitted")
