"""Auth header extraction and RBAC (PRD §2.1, §1.7)."""
from functools import wraps

from flask import request, g

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE

KNOWN_ROLES = {"Customer", "BakeryStaff", "DeliveryDispatcher", "BakeryManager"}
# Anonymous is a virtual role: it is what a caller presenting no/role=Anonymous gets.
ALL_ROLES_INCL_ANON = KNOWN_ROLES | {"Anonymous"}


def get_identity():
    """Read X-User-ID and X-User-Role from the request headers."""
    return request.headers.get("X-User-ID"), request.headers.get("X-User-Role")


def require_auth(allowed_roles):
    """Decorator: enforce authentication then role authorization.

    allowed_roles: iterable of role names permitted for the endpoint. If
    'Anonymous' is included, an unauthenticated caller is permitted.
    """
    allowed = set(allowed_roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_identity()

            # Authentication: both headers present and role is a known role.
            # Anonymous-permitted endpoints accept a caller with no headers.
            if role is None or user_id is None:
                if "Anonymous" in allowed:
                    g.user_id = user_id
                    g.role = "Anonymous"
                    return fn(*args, **kwargs)
                raise err(ERR_UNAUTHENTICATED, "missing X-User-ID or X-User-Role")

            if role not in ALL_ROLES_INCL_ANON:
                raise err(ERR_UNAUTHENTICATED, "unknown X-User-Role")

            # Role authorization for the endpoint.
            if role not in allowed:
                raise err(ERR_FORBIDDEN_ROLE, "role not permitted for this endpoint")

            g.user_id = user_id
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator
