"""Auth header extraction and RBAC (PRD §2.1, §2.9; SCAFFOLD §1.4, §1.7).

Every request must carry X-User-ID and X-User-Role. A request that omits
X-User-Role or presents an unrecognized role -> ERR_UNAUTHENTICATED (401).
A recognized role not permitted for the operation -> ERR_FORBIDDEN (403).
"""

from functools import wraps

from flask import g, request

from errors import err

ROLES = {"PlatformAdmin", "CodeOfficer", "HearingOfficer", "FinanceClerk", "Registrant"}


def authenticate():
    """Validate auth headers. Populates g.user_id and g.role. Raises on failure."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "X-User-Role header missing or not a declared role")
    g.role = role
    g.user_id = user_id


def require_roles(*allowed):
    """Decorator: authenticate, then enforce that the acting role is permitted.

    Auth (401) precedes authorization (403) per PRD §2.9 validation ordering.
    """

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            if g.role not in allowed:
                raise err("ERR_FORBIDDEN", "acting role not permitted for this operation")
            return fn(*args, **kwargs)

        return wrapper

    return decorator
