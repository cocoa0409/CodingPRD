"""Auth header extraction and role checking per PRD §2.1."""

from functools import wraps

from flask import g, request

from errors import auth_missing, forbidden


VALID_ROLES = {
    "Declarant",
    "CustomsOfficer",
    "FinanceOfficer",
    "Importer",
    "Auditor",
}


def extract_auth():
    """Pull X-User-ID and X-User-Role from the request, raising on failure."""
    user_id = request.headers.get("X-User-ID", "")
    role = request.headers.get("X-User-Role", "")
    if user_id is None or role is None or user_id.strip() == "" or role.strip() == "":
        raise auth_missing()
    user_id = user_id.strip()
    role = role.strip()
    g.user_id = user_id
    g.role = role
    return user_id, role


def require_roles(*roles):
    """Decorator: enforce the authenticated role is in the allowed set.

    The auth presence check has already been performed at request entry by a
    before_request hook (see app.py). Here we only enforce role authorization.
    """
    allowed = set(roles)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if getattr(g, "role", None) not in allowed:
                raise forbidden()
            return fn(*args, **kwargs)
        return wrapper
    return deco
