"""Authentication (X-User-ID / X-User-Role) and per-endpoint role checks."""
from functools import wraps

from flask import g, request

from errors import err_forbidden, err_unauthenticated

ROLES = ("TerminalAdmin", "Dispatcher", "DockSupervisor", "RatingClerk", "OsdClerk")


def authenticate():
    """before_request hook. Authentication precedes every other concern
    (PRD section 2.1, validation priority 1)."""
    if not request.path.startswith("/ltl"):
        return None
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err_unauthenticated()
    g.user_id = user_id
    g.user_role = role
    return None


def require_roles(*roles):
    """Authorization check (validation priority 2) for a route handler."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if g.user_role not in roles:
                raise err_forbidden(
                    "Role {} is not permitted to call this endpoint".format(g.user_role)
                )
            return fn(*args, **kwargs)
        return wrapper
    return decorator
