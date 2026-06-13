"""Auth header extraction and role checking (PRD §2.1).

Every request carries two mandatory headers:
  X-User-ID   — acting user id (Provider.id for Optometrist/Optician; opaque
                for FrontDesk/Biller)
  X-User-Role — one of FrontDesk, Optometrist, Optician, Biller
"""
from functools import wraps

from flask import request, g

import errors

KNOWN_ROLES = {"FrontDesk", "Optometrist", "Optician", "Biller"}


def authenticate():
    """Validate auth headers; populate g.user_id and g.user_role.

    Raises ERR_UNAUTHENTICATED when either header is missing or the role is not
    a known role.
    """
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if not user_id or not user_role:
        raise errors.unauthenticated()
    if user_role not in KNOWN_ROLES:
        raise errors.unauthenticated("Unknown role")
    g.user_id = user_id
    g.user_role = user_role


def require_roles(*allowed):
    """Decorator: authenticate, then enforce the acting role is permitted.

    Authentication (401) is checked before role authorization (403), per the
    validation ordering in PRD §2.6.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            if g.user_role not in allowed:
                raise errors.forbidden()
            return fn(*args, **kwargs)
        return wrapper
    return decorator
