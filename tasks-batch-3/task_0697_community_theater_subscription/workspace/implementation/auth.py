"""Authentication / RBAC helpers (PRD §2.1, §2.10).

Headers: X-User-ID (acting user) and X-User-Role (capacity). Both mandatory and
well-formed or ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400). Recognized roles
are exactly: SeasonAdmin, BoxOfficeAgent, Patron, ArtisticDirector.
"""
from flask import request

from errors import err, ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, ERR_UNAUTHORIZED

ROLES = {"SeasonAdmin", "BoxOfficeAgent", "Patron", "ArtisticDirector"}


def get_context():
    """Validate and return (user_id, role). Raises on missing/invalid header."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise err(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
    user_id = user_id.strip()
    role = role.strip()
    if not user_id or not role or role not in ROLES:
        raise err(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
    return user_id, role


def require_role(role, allowed):
    """Priority-2 RBAC role gate. `allowed` is a set/iterable of role names."""
    if role not in allowed:
        raise err(ERR_UNAUTHORIZED)
