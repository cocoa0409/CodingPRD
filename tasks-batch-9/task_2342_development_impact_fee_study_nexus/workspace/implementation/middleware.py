"""Authentication and authorization (PRD 2.1, precedence steps 1 and 2)."""

from functools import wraps

from flask import g, request

from errors import raise_error

ROLES = (
    "ProgramAdministrator",
    "NexusAnalyst",
    "CouncilClerk",
    "PermitOfficer",
    "Developer",
    "FinanceOfficer",
)

ANY = ROLES


def _header(name):
    value = request.headers.get(name)
    if value is None:
        return None
    return value


def authenticate():
    user_id = _header("X-User-ID")
    role = _header("X-User-Role")
    if user_id is None or not user_id.strip() or role is None or not role.strip():
        raise_error("ERR_UNAUTHENTICATED")
    return user_id, role


def guard(*roles):
    """Authenticate, then authorize the declared role for this endpoint."""
    allowed = roles if roles else ANY

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            user_id, role = authenticate()
            if role not in ROLES or role not in allowed:
                raise_error("ERR_UNAUTHORIZED")
            g.user_id = user_id
            g.role = role
            return view(*args, **kwargs)

        return wrapper

    return decorator


def open_guard(view):
    """The clock endpoint: no authentication, but a declared role must be real."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        role = _header("X-User-Role")
        if role is not None and role.strip() and role not in ROLES:
            raise_error("ERR_UNAUTHORIZED")
        g.user_id = _header("X-User-ID")
        g.role = role
        return view(*args, **kwargs)

    return wrapper


def current_user_id():
    return getattr(g, "user_id", None)
