"""Auth header extraction and role checking per PRD §2.1."""

from functools import wraps

from flask import g, request

from errors import auth_required, forbidden


VALID_ROLES = {
    "Initiator",
    "Backer",
    "ContentReviewer",
    "LegalReviewer",
    "FinancialReviewer",
    "PlatformAdmin",
}


def extract_auth():
    """Pull X-User-ID and X-User-Role from the request, raising on failure.

    Stores them on flask.g for downstream use.
    """
    user_id = request.headers.get("X-User-ID", "").strip()
    role = request.headers.get("X-User-Role", "").strip()
    if not user_id or not role:
        raise auth_required()
    if role not in VALID_ROLES:
        # Unknown role => not authorized for any endpoint
        raise forbidden(f"Unknown role: {role}")
    g.user_id = user_id
    g.role = role
    return user_id, role


def require_roles(*roles):
    """Decorator: enforce that the authenticated role is in the allowed set.

    The auth_required check has already been performed at request entry by
    a before_request hook (see app.py). Here we only check role authorization.
    """
    allowed = set(roles)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if g.role not in allowed:
                raise forbidden()
            return fn(*args, **kwargs)
        return wrapper
    return deco
