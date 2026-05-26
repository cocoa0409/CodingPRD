"""Auth header extraction and role checking."""
from flask import g, request

from errors import err_forbidden, err_unauth

VALID_ROLES = {"Commissioner", "TeamOwner"}


def authenticate():
    """Read X-User-ID and X-User-Role headers. Raise on missing/invalid.

    Stores results on `flask.g.user_id` and `flask.g.user_role`.
    """
    user_id = request.headers.get("X-User-ID") or ""
    user_role = request.headers.get("X-User-Role") or ""
    if not user_id.strip() or not user_role.strip():
        raise err_unauth()
    if user_role not in VALID_ROLES:
        raise err_forbidden("Unknown role.")
    g.user_id = user_id
    g.user_role = user_role


def require_role(*roles):
    """Raise ERR_FORBIDDEN if the caller's role is not one of `roles`."""
    if g.user_role not in roles:
        raise err_forbidden(f"Role {g.user_role!r} not permitted.")


def require_team_owner_self(team_id: str):
    """For TeamOwner-only actions on a specific team, X-User-ID must match."""
    if g.user_role == "TeamOwner" and g.user_id != team_id:
        raise err_forbidden("TeamOwner may only act on their own team.")
