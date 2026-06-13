"""Auth header extraction and role checking (PRD §2.1, §2.9).

Two mandatory headers:
  X-User-ID   -- acting user id
  X-User-Role -- one of {FrontDeskClerk, RepairTechnician, ShopManager, Customer}

If either is missing or malformed -> ERR_MISSING_AUTH_CONTEXT (401).
If the role is not permitted for the operation -> ERR_FORBIDDEN_ROLE (403).
"""
from flask import request

from errors import ApiError

VALID_ROLES = {"FrontDeskClerk", "RepairTechnician", "ShopManager", "Customer"}


def get_auth():
    """Return (user_id, role); raise ERR_MISSING_AUTH_CONTEXT if missing/malformed."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise ApiError("ERR_MISSING_AUTH_CONTEXT", "Missing X-User-ID or X-User-Role header")
    if not isinstance(user_id, str) or user_id.strip() == "":
        raise ApiError("ERR_MISSING_AUTH_CONTEXT", "Malformed X-User-ID header")
    if role not in VALID_ROLES:
        raise ApiError("ERR_MISSING_AUTH_CONTEXT", "Malformed X-User-Role header")
    return user_id, role


def require_roles(role, allowed):
    """Raise ERR_FORBIDDEN_ROLE if the acting role is not in allowed."""
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN_ROLE", "Role %s not permitted for this operation" % role)
