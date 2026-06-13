"""Auth header extraction + role checking (PRD §2.1).

Headers (verbatim from PRD §2.1):
  X-User-ID   — calling principal id. Opaque for FrontDesk; for the three
                entity-backed roles it is the acting entity's id.
  X-User-Role — one of: FrontDesk, Instructor, ChiefInstructor, Member
"""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

ROLE_FRONTDESK = "FrontDesk"
ROLE_INSTRUCTOR = "Instructor"
ROLE_CHIEF = "ChiefInstructor"
ROLE_MEMBER = "Member"

VALID_ROLES = {ROLE_FRONTDESK, ROLE_INSTRUCTOR, ROLE_CHIEF, ROLE_MEMBER}
# Roles whose X-User-ID must be present (entity-backed identity).
ENTITY_BACKED_ROLES = {ROLE_INSTRUCTOR, ROLE_CHIEF, ROLE_MEMBER}


def get_identity():
    """Return (user_id, role). Raises ERR_UNAUTHENTICATED if:
      - X-User-Role is missing or not one of the four recognized roles, or
      - X-User-ID is missing for an entity-backed role.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not role or role not in VALID_ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or unknown X-User-Role header.")
    if role in ENTITY_BACKED_ROLES and not user_id:
        raise err(ERR_UNAUTHENTICATED, "Missing X-User-ID for an entity-backed role.")
    return user_id, role


def require_roles(role, allowed):
    """Authorization gate (ERR_UNAUTHORIZED). `allowed` is an iterable of role
    names permitted for the operation."""
    if role not in allowed:
        raise err(ERR_UNAUTHORIZED, "Role not permitted for this operation.")
