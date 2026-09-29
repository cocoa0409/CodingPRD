"""Auth header extraction and role checking (PRD 2.1, ladder rungs 1-3)."""

import uuid
from functools import wraps

from flask import g, request

from errors import ApiError

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

ROLES = (
    "CampaignManager",
    "ComplianceModerator",
    "FulfillmentOps",
    "Panelist",
    "PlatformAdmin",
    "Anonymous",
)


def _valid_uuid(value):
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def authenticate(allowed_roles, anonymous_ok=False):
    role = request.headers.get(USER_ROLE_HEADER)
    user_id = request.headers.get(USER_ID_HEADER)
    role = role.strip() if isinstance(role, str) else role
    user_id = user_id.strip() if isinstance(user_id, str) else user_id

    if anonymous_ok:
        # Panel sign-up is the one endpoint reachable without an established
        # identity (PRD 2.1 / 1.7).
        if not role:
            role = "Anonymous"
        if role not in ROLES:
            raise ApiError("ERR_UNAUTHENTICATED", "Unknown role '%s'" % role)
        if role != "Anonymous":
            if not user_id:
                raise ApiError("ERR_UNAUTHENTICATED",
                               "%s header is required" % USER_ID_HEADER)
            if not _valid_uuid(user_id):
                raise ApiError("ERR_UNAUTHENTICATED",
                               "%s must be a valid UUID" % USER_ID_HEADER)
    else:
        # Rung 1: both headers present, non-empty, X-User-ID a valid UUID.
        if not user_id:
            raise ApiError("ERR_UNAUTHENTICATED",
                           "%s header is required" % USER_ID_HEADER)
        if not _valid_uuid(user_id):
            raise ApiError("ERR_UNAUTHENTICATED",
                           "%s must be a valid UUID" % USER_ID_HEADER)
        if not role:
            raise ApiError("ERR_UNAUTHENTICATED",
                           "%s header is required" % USER_ROLE_HEADER)
        # Rung 2: the role must be one of the six recognised values.
        if role not in ROLES:
            raise ApiError("ERR_UNAUTHENTICATED", "Unknown role '%s'" % role)

    g.role = role
    g.user_id = user_id or None

    # Rung 3: the role must be authorized for this endpoint.
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE",
                       "Role '%s' may not perform this operation" % role)


def endpoint(roles, anonymous_ok=False):
    """Decorator applying ladder rungs 1-3 before the handler body runs."""
    allowed = tuple(roles)

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            authenticate(allowed, anonymous_ok=anonymous_ok)
            return func(*args, **kwargs)
        return wrapper
    return decorator


def acting_user_id():
    return getattr(g, "user_id", None)


def acting_role():
    return getattr(g, "role", None)
