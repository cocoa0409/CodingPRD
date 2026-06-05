"""Auth header extraction and role checking."""
from flask import request

from db import db
from errors import err

VALID_ROLES = {"ListingAgent", "BuyerAgent", "Anonymous"}


def get_role():
    return request.headers.get("X-User-Role")


def get_user_id():
    return request.headers.get("X-User-ID")


def authenticate(allowed_roles):
    """Validate auth headers for a protected endpoint.

    allowed_roles: set/list of roles permitted for this operation.
    Returns (role, user_id). For agent roles user_id must resolve to an Agent.

    Priority: ERR_UNAUTHENTICATED (401) before ERR_FORBIDDEN_ROLE (403).
    """
    role = get_role()
    user_id = get_user_id()

    # Missing/invalid headers -> 401
    if not role or not user_id or role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid auth headers")

    # Agent roles must resolve to a registered Agent
    if role in ("ListingAgent", "BuyerAgent"):
        if user_id not in db.agents:
            raise err("ERR_UNAUTHENTICATED", "X-User-ID does not resolve to an Agent")

    # Role permitted for this operation?
    if role not in allowed_roles:
        raise err("ERR_FORBIDDEN_ROLE", "Role not permitted for this operation")

    return role, user_id
