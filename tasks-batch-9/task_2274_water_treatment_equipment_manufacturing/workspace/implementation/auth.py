"""Authentication / authorisation (PRD 2.8).

Identity is the opaque ``X-User-ID`` header; the caller's role is the
``X-User-Role`` header.  Both must be present and non-empty or the request is
unauthenticated (ladder tier 1).  Role membership is checked next (tier 2),
before any path id is resolved.
"""
import functools

from flask import g, request

from errors import fail

ROLES = (
    "PlatformAdmin",
    "ApplicationEngineer",
    "QualityEngineer",
    "DesignReviewer",
    "FabricationManager",
    "EngineerOfRecord",
    "ContractsAdministrator",
    "CommissioningEngineer",
    "OwnerRepresentative",
)

ALL_ROLES = ROLES


def _header(name):
    value = request.headers.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def authenticate():
    user_id = _header("X-User-ID")
    role = _header("X-User-Role")
    if not user_id or not role:
        fail("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role headers are required")
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role %s is not a declared role" % role)
    g.user_id = user_id
    g.user_role = role
    return user_id, role


def current_user_id():
    return getattr(g, "user_id", None)


def current_role():
    return getattr(g, "user_role", None)


def require(*allowed):
    """Authenticate, then assert the caller's role is one of ``allowed``."""
    _, role = authenticate()
    if role not in allowed:
        fail("ERR_UNAUTHORIZED", "role %s may not perform this operation" % role)
    return current_user_id()


def roles(*allowed):
    """Decorator form of :func:`require`."""
    if not allowed:
        allowed = ROLES

    def decorate(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            require(*allowed)
            return fn(*args, **kwargs)
        return wrapper
    return decorate


def any_role(fn):
    """Read endpoints: every one of the nine roles may call them."""
    return roles(*ROLES)(fn)
