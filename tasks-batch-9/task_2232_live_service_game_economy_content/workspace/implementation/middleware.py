"""Authentication / authorization (PRD 2.1, precedence steps 1-2 and 6)."""
from flask import request

from config import ALL_ROLES, ROLE_PLAYER
from errors import fail


def authenticate(*allowed_roles):
    """Step 1 (ERR_UNAUTHENTICATED) then step 2 (ERR_UNAUTHORIZED)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ALL_ROLES:
        fail("ERR_UNAUTHENTICATED")
    if allowed_roles and role not in allowed_roles:
        fail("ERR_UNAUTHORIZED")
    return user_id, role


def require_owner(role, user_id, owner_player_id):
    """Step 6: a Player acts only on its own resources."""
    if role == ROLE_PLAYER and user_id != owner_player_id:
        fail("ERR_NOT_RESOURCE_OWNER")
