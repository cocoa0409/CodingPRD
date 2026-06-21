"""Auth header extraction and role checking (PRD §2.1).

Two mandatory headers: X-User-ID identifies the operator, X-User-Role declares
the role. Five recognized roles, spelled exactly:
  PlatformAdmin, FloorManager, DoorHost, Bartender, SecurityOfficer.

Missing X-User-ID, missing X-User-Role, or an unknown role value -> 401
ERR_UNAUTHENTICATED. A well-formed but unpermitted role -> 403 ERR_FORBIDDEN_ROLE.

All five roles are opaque operator identities; X-User-ID is never matched
against any stored entity. Authorization is purely role-based.
"""
from flask import request

import errors

VALID_ROLES = {
    "PlatformAdmin",
    "FloorManager",
    "DoorHost",
    "Bartender",
    "SecurityOfficer",
}


def get_auth():
    """Priority 1 (PRD §3.10): both headers present and X-User-Role is a known role.

    Returns (role, user_id).
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if user_id is None or user_id == "":
        raise errors.unauthenticated("X-User-ID header missing")
    if role is None or role not in VALID_ROLES:
        raise errors.unauthenticated("X-User-Role header missing or invalid")
    return role, user_id


def require_roles(role, allowed):
    """Priority 2 (PRD §3.10): acting role permitted for this operation per RBAC."""
    if role not in allowed:
        raise errors.forbidden_role(f"Role {role} not permitted for this operation")
