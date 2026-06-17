"""Auth header extraction and role checking.

Auth headers (PRD §2.1): X-User-ID and X-User-Role.
Recognized roles: Admin, SalesRep, Estimator, Scheduler, Customer.
"""
import functools

from flask import g, request

from errors import err

KNOWN_ROLES = {"Admin", "SalesRep", "Estimator", "Scheduler", "Customer"}


def authenticate():
    """Validate auth headers; populate g.user_id / g.user_role.

    Raises ERR_UNAUTHENTICATED (401) if either header is missing or the role
    is not one of the recognized roles.
    """
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if not user_id or not user_role or user_role not in KNOWN_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid user-context headers.")
    g.user_id = user_id
    g.user_role = user_role
    return user_id, user_role


def require_roles(*allowed_roles):
    """Decorator: authenticate, then enforce that the acting role is allowed.

    Admin is always allowed (operational override per RBAC matrix) — but only
    where Admin is in the allowed set or the matrix grants override. The PRD
    endpoint table lists Admin explicitly wherever it is permitted, so we honor
    the declared set exactly (and the table already includes Admin where it
    applies).
    """

    allowed = set(allowed_roles)

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            if g.user_role not in allowed:
                raise err(
                    "ERR_FORBIDDEN_ROLE",
                    "Role '%s' is not permitted for this operation." % g.user_role,
                )
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def anonymous_or_admin(fn):
    """Registration endpoints: open to an unauthenticated caller or to Admin.

    If auth headers are present they must be valid (a present-but-bad role is
    rejected), and only Admin among authenticated roles may call. If no headers
    at all, the caller is treated as Anonymous and allowed.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        user_id = request.headers.get("X-User-ID")
        user_role = request.headers.get("X-User-Role")
        if user_id is None and user_role is None:
            # Pure anonymous caller — allowed.
            g.user_id = None
            g.user_role = "Anonymous"
            return fn(*args, **kwargs)
        # Some auth context supplied: it must be a valid, recognized identity.
        authenticate()
        if g.user_role != "Admin":
            raise err(
                "ERR_FORBIDDEN_ROLE",
                "Only Admin or an anonymous caller may register.",
            )
        return fn(*args, **kwargs)

    return wrapper
