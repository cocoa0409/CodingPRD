"""Auth header extraction + RBAC (PRD §2.1, §2.9).

Every request that is not an open self-registration must carry X-User-ID and
X-User-Role. The five recognized roles are Customer, Pro, PlatformAdmin,
Dispatcher, Anonymous.

Validation order (PRD §2.9): request-body well-formedness (handled per-route)
first, then authentication (header presence + known role -> ERR_UNAUTHENTICATED,
401), then role permission (ERR_UNAUTHORIZED, 403), then existence, then
semantic body, then ownership, then state, then business rules.

Self-registration endpoints (POST /customers, POST /pros, POST
/service-categories) are exempt from authentication. POST /customers and
POST /pros are reachable by the Anonymous role; POST /service-categories is a
PlatformAdmin operation but the PRD lists it among the no-auth-required
endpoints — it is treated as PlatformAdmin-only, and missing headers default the
caller to the permitted admin context for that one route.
"""
from functools import wraps
from flask import request, g

from errors import ApiError

VALID_ROLES = {
    "Customer",
    "Pro",
    "PlatformAdmin",
    "Dispatcher",
    "Anonymous",
}


def _read_headers():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    return user_id, role


def require_auth():
    """Validate the user-context headers. Raises ERR_UNAUTHENTICATED (401) when a
    header is missing/blank or X-User-Role is not a known role. Stores the
    acting id+role on flask.g."""
    user_id, role = _read_headers()
    if not user_id or not isinstance(user_id, str) or user_id.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header missing")
    if not role or role not in VALID_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header missing or unknown")
    g.user_id = user_id
    g.role = role
    return user_id, role


def require_role(allowed_roles, validate=None):
    """Decorator: optionally validate request-body shape, then authenticate, then
    enforce role membership.

    PRD §2.9 pins the global order as (1) request-body well-formedness
    (ERR_INVALID_REQUEST), (2) authentication (ERR_UNAUTHENTICATED), (3) role
    permission (ERR_UNAUTHORIZED). So when a `validate` callback is supplied it
    runs FIRST — a malformed body is reported before any auth problem. The
    callback receives the parsed body dict and returns a dict of validated
    values, which is stashed on flask.g.validated for the view to consume.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if validate is not None:
                from services.lookup import require_body
                g.validated = validate(require_body())
            require_auth()
            if g.role not in allowed_roles:
                raise ApiError("ERR_UNAUTHORIZED",
                               "Role %s is not permitted for this operation" % g.role)
            return fn(*args, **kwargs)
        return wrapper
    return decorator
