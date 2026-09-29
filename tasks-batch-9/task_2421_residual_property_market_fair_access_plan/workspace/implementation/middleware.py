"""Authentication (rung 1) and role authorization (rung 2) — PRD 2.1 / 2.11."""

from flask import request

from errors import fail

# PRD 2.1 — the eight declared roles.
ROLES = (
    "PlanAdmin",
    "Producer",
    "Underwriter",
    "Inspector",
    "RateAnalyst",
    "Regulator",
    "MemberInsurerUser",
    "Policyholder",
)


class Caller(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not str(user_id).strip():
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is required")
    if not role or not str(role).strip():
        fail("ERR_UNAUTHENTICATED", "X-User-Role header is required")
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role '%s' is not a declared role" % role)
    return Caller(user_id, role)


def require(*allowed_roles):
    """Rungs 1 and 2 of the precedence ladder, in that order."""
    caller = authenticate()
    if caller.role not in allowed_roles:
        fail("ERR_FORBIDDEN_ROLE",
             "Role '%s' is not authorized for this operation" % caller.role)
    return caller


def own(condition, message="Caller does not own this resource"):
    """Rung 6 — entity-backed ownership."""
    if not condition:
        fail("ERR_NOT_RESOURCE_OWNER", message)
