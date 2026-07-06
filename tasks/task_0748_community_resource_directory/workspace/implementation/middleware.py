"""Auth extraction and RBAC role checks."""
from functools import wraps

from flask import request

from errors import (
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
    raise_error,
)


VALID_ROLES = {"PlatformAdmin", "Caseworker", "ProviderStaff", "Client", "FunderReporter"}

# Which roles are "entity-backed" — their X-User-ID is compared to an owner FK.
ENTITY_BACKED = {"ProviderStaff", "Client", "FunderReporter"}


def get_auth() -> tuple[str, str]:
    """Extract and validate X-User-ID / X-User-Role. Raises ERR_UNAUTHENTICATED."""
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or not uid:
        raise_error(ERR_UNAUTHENTICATED, "missing X-User-Role or X-User-ID")
    if role not in VALID_ROLES:
        raise_error(ERR_UNAUTHENTICATED, "unrecognised X-User-Role")
    return uid, role


def require_roles(*allowed: str):
    """Decorator that enforces the endpoint's allowed roles. Also extracts auth."""

    def wrap(fn):
        @wraps(fn)
        def inner(*args, **kwargs):
            uid, role = get_auth()
            if role not in allowed:
                raise_error(ERR_UNAUTHORIZED, f"role {role} not permitted")
            return fn(*args, **kwargs)

        return inner

    return wrap
