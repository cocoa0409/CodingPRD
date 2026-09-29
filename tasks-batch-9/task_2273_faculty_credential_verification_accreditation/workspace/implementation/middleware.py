"""Auth header extraction and the RBAC / ownership rungs (PRD 2.1)."""

from flask import g, request

from constants import ENTITY_BACKED_ROLES, INSTRUCTOR, PROGRAM_DEAN
from errors import ApiError

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


def load_identity():
    """Rung 1: X-User-ID must be present and non-empty."""
    g.touched = set()
    user_id = request.headers.get(USER_ID_HEADER)
    if user_id is not None:
        user_id = user_id.strip()
    if not user_id:
        raise ApiError("ERR_UNAUTHENTICATED")
    g.user_id = user_id
    role = request.headers.get(USER_ROLE_HEADER)
    g.user_role = role.strip() if isinstance(role, str) else None


def user_id():
    return g.get("user_id")


def role():
    return g.get("user_role")


def require_role(*allowed):
    """Rung 2: X-User-Role must be present and authorized for the endpoint."""
    current = role()
    if not current or current not in allowed:
        raise ApiError("ERR_FORBIDDEN_ROLE")
    return current


def is_entity_backed():
    return role() in ENTITY_BACKED_ROLES


def require_dean_owns(program_id):
    """Rung 3 for a ProgramDean; opaque roles skip the ownership rule."""
    if role() != PROGRAM_DEAN:
        return
    if program_id is None:
        return
    if user_id() != program_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def require_instructor_owns(faculty_member_id):
    if role() != INSTRUCTOR:
        return
    if faculty_member_id is None:
        return
    if user_id() != faculty_member_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def require_owner(program_id=None, faculty_member_id=None):
    require_dean_owns(program_id)
    require_instructor_owns(faculty_member_id)
