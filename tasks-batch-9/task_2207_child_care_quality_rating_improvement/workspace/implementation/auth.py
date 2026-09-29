"""Authentication and role authorization (PRD §2.1, §2.7 steps 1-2)."""

from flask import request

from errors import fail

ROLES = (
    "StateAdministrator",
    "Provider",
    "Observer",
    "Coach",
    "AppealReviewer",
    "FamilyViewer",
)


class Principal(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_admin(self):
        return self.role == "StateAdministrator"

    @property
    def is_provider(self):
        return self.role == "Provider"

    @property
    def is_observer(self):
        return self.role == "Observer"


def authenticate():
    """Step 1: X-User-Role present and a declared role; X-User-ID present unless FamilyViewer."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role == "" or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role must be present and name a declared role")
    if role != "FamilyViewer" and (user_id is None or user_id == ""):
        fail("ERR_UNAUTHENTICATED", "X-User-ID is required for role %s" % role)
    return Principal(user_id, role)


def authorize(principal, allowed):
    """Step 2: acting role must appear in the endpoint's permitted-role list."""
    if principal.role not in allowed:
        fail("ERR_FORBIDDEN_ROLE", "role %s may not perform this operation" % principal.role)
    return principal


def require(*allowed):
    """Authenticate then authorize in one call, returning the principal."""
    principal = authenticate()
    authorize(principal, allowed)
    return principal
