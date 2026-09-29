"""Authentication / RBAC (PRD 2.1, enforcement bands 1-3)."""

from flask import request

from constants import ROLES
from db import db
from errors import fail


def authenticate(allowed_roles):
    """Bands 1-3.  Returns (user_id, role)."""
    role = request.headers.get("X-User-Role")
    if role is None or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role is missing or not a recognised role")

    user_id = request.headers.get("X-User-ID")
    if user_id is None or user_id == "":
        fail("ERR_UNAUTHENTICATED", "X-User-ID is missing or empty")
    if role == "Student" and user_id not in db.students:
        fail("ERR_UNAUTHENTICATED", "X-User-ID does not name an existing student record")

    if role not in allowed_roles:
        fail("ERR_UNAUTHORIZED", "role %s may not perform this operation" % role)

    return user_id, role
