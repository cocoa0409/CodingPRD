"""Ladder steps 1-3: header authentication, endpoint role authorisation and
InstitutionAdmin scope (PRD 2.1 / 2.9)."""

from flask import request

from constants import ROLES
from errors import fail


def authenticate(allowed_roles):
    """Steps 1 and 2 of PRD 2.9.  Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        fail("ERR_FORBIDDEN_ROLE")
    return user_id, role


def institution_scope(user_id, role, institution_id):
    """Step 3 of PRD 2.9 -- runs before path identifier resolution."""
    if role == "InstitutionAdmin" and institution_id != user_id:
        fail("ERR_INSTITUTION_SCOPE_VIOLATION")
