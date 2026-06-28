"""Auth header extraction and RBAC (PRD §2.1, §2.9, SCAFFOLD §1.4 / §1.7).

Headers:
  X-User-ID   — acting principal id
  X-User-Role — one of OpsAdmin | AccountHolder | Inspector

Validation priority (PRD §2.9):
  1. ERR_UNAUTHENTICATED (401) — headers missing/invalid role
  2. ERR_FORBIDDEN_ROLE   (403) — role not permitted for endpoint
  (existence, ownership, body, OCC, state, business follow per-endpoint)
"""
from functools import wraps

from flask import g, request

from errors import err

VALID_ROLES = {"OpsAdmin", "AccountHolder", "Inspector"}


def authenticate():
    """Resolve and validate the auth headers; populate flask.g.

    Raises ERR_UNAUTHENTICATED if either header is missing or role unknown.
    """
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if not user_id or not user_role or user_role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers")
    g.user_id = user_id
    g.user_role = user_role
    return user_id, user_role


def require_roles(*allowed_roles):
    """Decorator: authenticate, then enforce role membership for the endpoint."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            if g.user_role not in allowed_roles:
                raise err(
                    "ERR_FORBIDDEN_ROLE",
                    "Role '%s' is not permitted for this operation" % g.user_role,
                )
            return fn(*args, **kwargs)
        return wrapper
    return decorator
