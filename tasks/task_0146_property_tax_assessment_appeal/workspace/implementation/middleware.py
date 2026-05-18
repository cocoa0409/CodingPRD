"""Auth middleware and helpers for header parsing + RBAC."""

from flask import g, request

from config import VALID_ROLES
from db import store
from errors import raise_error


def authenticate():
    """Validates auth headers and stashes user context on `g`.

    Returns None on success; raises APIError on failure.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise_error("ERR_UNAUTHENTICATED")
    if role not in VALID_ROLES:
        raise_error("ERR_FORBIDDEN")
    g.user_id = user_id
    g.role = role


def require_roles(allowed_roles):
    """Raises ERR_FORBIDDEN if g.role is not in allowed_roles."""
    role = getattr(g, "role", None)
    if role not in allowed_roles:
        raise_error("ERR_FORBIDDEN")


def require_owner_of_property(property_id: str):
    """For Owner-scoped writes, verify X-User-ID matches Property.owner_id.

    Caller should have already verified property existence.
    Raises ERR_OWNERSHIP_MISMATCH on failure. Does nothing for non-Owner roles
    (those should not have reached this check unless authorized).
    """
    if g.role != "Owner":
        return
    prop = store.properties.get(property_id)
    if prop is None:
        # Should have been caught earlier
        raise_error("ERR_NOT_FOUND")
    if prop["owner_id"] != g.user_id:
        raise_error("ERR_OWNERSHIP_MISMATCH")


def acting_user_id() -> str:
    return g.user_id


def acting_role() -> str:
    return g.role
