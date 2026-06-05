"""Auth header extraction and RBAC (PRD §2.1, §2.7).

Auth gate order (priorities 1 and 2):
  1. ERR_UNAUTHENTICATED (401): X-User-ID and X-User-Role headers present and
     well-formed (role is one of the three recognised roles).
  2. ERR_FORBIDDEN (403): the acting role is permitted for the operation;
     Member ownership on member-scoped resources.

The role-permission check happens at the route via require_roles(); ownership
checks happen inside the route handlers because they depend on the resource.
"""
from flask import request

from errors import err

VALID_ROLES = {"FleetManager", "RentalAgent", "Member"}


def get_principal():
    """Return (user_id, role) after the auth gate. Raises ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or user_id.strip() == "":
        raise err("ERR_UNAUTHENTICATED", "missing or malformed X-User-ID header")
    if not role or role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "missing or malformed X-User-Role header")
    return user_id, role


def require_roles(role, allowed):
    """ERR_FORBIDDEN (403) when the acting role is not in the allowed set."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN", "role %s is not permitted for this operation" % role)
