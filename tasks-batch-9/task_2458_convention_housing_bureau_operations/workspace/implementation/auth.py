"""Header authentication and role authorization (PRD §2.1, §2.10 steps 1-2)."""

from flask import request

from errors import fail
from store import ROLES


class Principal:
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate(allowed_roles):
    """Step 1 — both headers present and role one of the six declared names.
    Step 2 — the acting role appears in the endpoint's authorised list."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        fail("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role headers are required")
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "unrecognised X-User-Role: %s" % role)
    if role not in allowed_roles:
        fail("ERR_UNAUTHORIZED", "role %s is not authorised for this endpoint" % role)
    return Principal(user_id, role)
