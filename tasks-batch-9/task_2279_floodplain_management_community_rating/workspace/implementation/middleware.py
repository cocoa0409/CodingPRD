"""Authentication (PRD 2.1) and role authorization (PRD 2.8 steps 1-2)."""

from flask import request

from errors import fail

ROLES = (
    "StateNfipCoordinator",
    "FloodplainAdministrator",
    "PropertyOwner",
    "AppealsBoardMember",
)

ALL_ROLES = ROLES
READ_ROLES = ROLES


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not str(user_id).strip():
        fail("ERR_UNAUTHENTICATED")
    if role is None or not str(role).strip():
        fail("ERR_UNAUTHENTICATED")
    role = role.strip()
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED")
    return str(user_id).strip(), role


def require(*allowed):
    """Steps 1 and 2 of PRD 2.8 — returns (user_id, role)."""
    user_id, role = authenticate()
    if role not in allowed:
        fail("ERR_ROLE_NOT_PERMITTED")
    return user_id, role
