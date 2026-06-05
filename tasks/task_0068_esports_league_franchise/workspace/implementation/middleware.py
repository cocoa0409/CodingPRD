from flask import request
from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE

VALID_ROLES = {"LeagueCommissioner", "TeamGM"}


def get_auth():
    """Validate auth headers. Returns (role, user_id). Raises on failure."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id or role not in VALID_ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or invalid authentication headers.")
    return role, user_id


def require_role(role, allowed):
    if role not in allowed:
        raise err(ERR_FORBIDDEN_ROLE, "Role not permitted for this operation.")
