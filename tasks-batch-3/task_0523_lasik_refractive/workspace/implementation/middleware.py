from functools import wraps
from flask import request, g

from errors import err

VALID_ROLES = {"Coordinator", "Surgeon", "Optometrist", "Patient", "Anonymous"}


def get_auth():
    """Return (user_id, role) from headers, or (None, None)."""
    return request.headers.get("X-User-ID"), request.headers.get("X-User-Role")


def require_auth(allowed_roles):
    """Decorator enforcing auth (401) then role permission (403).

    allowed_roles: iterable of role names permitted to call this endpoint.
    If 'Anonymous' is in allowed_roles, unauthenticated callers are permitted.
    """
    allowed = set(allowed_roles)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_auth()
            anon_ok = "Anonymous" in allowed

            # Auth: both headers must be present, unless the endpoint is open
            # to Anonymous (registration/health).
            if not user_id or not role or role not in VALID_ROLES:
                if anon_ok:
                    # Open endpoint: allow through as Anonymous even without headers.
                    g.user_id = user_id
                    g.role = role if role in VALID_ROLES else "Anonymous"
                    return fn(*args, **kwargs)
                raise err("ERR_UNAUTHENTICATED", "Missing or invalid X-User-ID / X-User-Role")

            if role not in allowed:
                raise err("ERR_FORBIDDEN", "Role %s not permitted for this operation" % role)

            g.user_id = user_id
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return deco
