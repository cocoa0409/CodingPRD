"""Auth context extraction and role checks (PRD §2.1, §2.6)."""
from flask import request

from errors import ApiError

VALID_ROLES = {"AuctionAdmin", "Seller", "Buyer", "Arbitrator"}


def get_auth():
    """Return (user_id, role) or raise ERR_MISSING_AUTH_CONTEXT.

    Both X-User-ID and X-User-Role must be present, non-empty, and the role must
    be one of the four recognized roles.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise ApiError("ERR_MISSING_AUTH_CONTEXT", "Missing authentication context.")
    user_id = user_id.strip()
    role = role.strip()
    if user_id == "" or role == "":
        raise ApiError("ERR_MISSING_AUTH_CONTEXT", "Missing authentication context.")
    if role not in VALID_ROLES:
        raise ApiError("ERR_MISSING_AUTH_CONTEXT", "Malformed role value.")
    return user_id, role


def require_role(role, allowed):
    """Raise ERR_FORBIDDEN_ROLE if role not in allowed set."""
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN_ROLE", "Role not permitted for this operation.")
