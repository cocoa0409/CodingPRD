"""Authentication, role authorization and ArtistRep row scoping (ranks 1-3, 9)."""

import functools

from flask import g, request

from errors import fail

ROLES = (
    "TalentBuyer",
    "ArtistRep",
    "BusinessAffairs",
    "ProductionManager",
    "FinanceController",
)

ALL_ROLES = list(ROLES)


def _header(name):
    value = request.headers.get(name)
    if value is None:
        return None
    return value


def authorize(allowed_roles):
    """Ranks 1-3 of the precedence ladder, evaluated before any body parse."""
    user_id = _header("X-User-Id")
    role = _header("X-User-Role")

    if user_id is None or str(user_id).strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-Id header is required")
    if role is None or str(role).strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-Role header is required")
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role is not a recognised role")
    if role not in allowed_roles:
        fail("ERR_ROLE_NOT_PERMITTED", "role %s may not call this endpoint" % role)

    g.user_id = user_id
    g.role = role


def endpoint(roles):
    """Decorator wiring the auth ladder in front of a route handler."""
    allowed = list(roles)

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            authorize(allowed)
            return view(*args, **kwargs)

        return wrapper

    return decorator


def is_artist_rep():
    return getattr(g, "role", None) == "ArtistRep"


def require_artist_scope(artist_id):
    """Rank 9 - row-level ownership, only evaluable once the row was found."""
    if is_artist_rep() and g.user_id != artist_id:
        fail("ERR_ARTIST_SCOPE_VIOLATION", "caller is confined to their own act")
