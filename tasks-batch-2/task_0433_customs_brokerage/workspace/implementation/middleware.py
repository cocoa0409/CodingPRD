"""Auth header extraction and role checking (PRD §2.1, §2.8).

Every request must carry X-User-ID and X-User-Role. If either header is missing,
or X-User-Role is not one of the four known roles, -> ERR_UNAUTHENTICATED (401).
When headers are well-formed but the role is not permitted for the operation ->
ERR_UNAUTHORIZED (403).
"""
from functools import wraps

from flask import request, g

from errors import err

KNOWN_ROLES = {"AccountAdmin", "ImporterUser", "LicensedBroker", "CBPOfficer"}


def authenticate():
    """Validate the auth header pair; populate g.user_id / g.user_role.

    Raises ERR_UNAUTHENTICATED on any failure.
    """
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if not user_id or not user_role or user_role not in KNOWN_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers.")
    g.user_id = user_id
    g.user_role = user_role
    return user_id, user_role


def check_importer_ownership(importer):
    """Business-referential ownership check (PRD §2.1, priority 4).

    An ImporterUser may only act on / file against an importer whose
    owner_user_id equals its X-User-ID. Other roles are not ownership-scoped on
    these writes. Checked after existence (404), before state (409).
    """
    if g.user_role == "ImporterUser" and importer["owner_user_id"] != g.user_id:
        raise err(
            "ERR_NOT_RESOURCE_OWNER",
            "ImporterUser may only act on an importer it owns.",
        )


def require_roles(*allowed_roles):
    """Decorator: authenticate, then enforce that g.user_role is allowed.

    Authentication (401) is always checked before authorization (403).
    """
    allowed = set(allowed_roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            if g.user_role not in allowed:
                raise err(
                    "ERR_UNAUTHORIZED",
                    "Role %s is not permitted for this operation." % g.user_role,
                )
            return fn(*args, **kwargs)

        return wrapper

    return decorator
