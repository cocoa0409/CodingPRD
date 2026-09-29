"""Authentication / authorisation middleware (PRD 2.1, validation ranks 1-3)."""

import functools

from flask import g, request

from constants import (
    ALL_ROLES,
    ROLE_TO_ORG_ROLE,
    STAKEHOLDER_BACKED_ROLES,
)
from db import db
from errors import ApiError


def authenticate(allowed_roles, skip_identity=False):
    # Rank 1 -- headers present and X-User-Role a declared role.
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers.")

    # Rank 2 -- the acting role is authorised for this endpoint.
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", "Role %s may not call this endpoint." % role)

    g.user_id = user_id
    g.role = role
    g.actor = None

    # Rank 3 -- stakeholder identity resolution for the five stakeholder-backed
    # roles.  PlatformAdmin is opaque and is never resolved.
    if role in STAKEHOLDER_BACKED_ROLES and not skip_identity:
        actor = db.stakeholders.get(user_id)
        if actor is None or actor["status"] != "ACTIVE":
            raise ApiError(
                "ERR_ROLE_IDENTITY_MISMATCH",
                "X-User-ID does not resolve to an ACTIVE stakeholder.",
            )
        if ROLE_TO_ORG_ROLE[role] not in (actor.get("org_roles") or []):
            raise ApiError(
                "ERR_ROLE_IDENTITY_MISMATCH",
                "Acting stakeholder does not hold the %s organisational role."
                % ROLE_TO_ORG_ROLE[role],
            )
        g.actor = actor


def endpoint(roles, skip_identity=False):
    """Decorator applying ranks 1-3 before the handler body runs."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate(roles, skip_identity=skip_identity)
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def actor_id():
    return g.user_id


def acting_stakeholder():
    return getattr(g, "actor", None)
