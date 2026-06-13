"""Auth (PRD §2.1) and request-body helpers.

Headers: X-User-ID, X-User-Role. Roles: MarketAdmin, MarketManager, Vendor.
"""
from flask import request

from errors import err

KNOWN_ROLES = {"MarketAdmin", "MarketManager", "Vendor"}


def get_auth():
    """Priority 1: ERR_UNAUTHENTICATED if either header missing or role unknown.

    Returns (user_id, role).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers")
    return user_id, role


def require_role(role, allowed):
    """Priority 2: ERR_FORBIDDEN_ROLE if role not in allowed set."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", "Role not permitted for this operation")


def get_json_body():
    """Parse JSON body; tolerate empty body as {}."""
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        raise err("ERR_INVALID_REQUEST", "Malformed JSON body")
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body
