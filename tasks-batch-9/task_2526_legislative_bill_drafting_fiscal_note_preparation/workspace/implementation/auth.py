"""Authentication, endpoint RBAC and seniority (PRD S2.1 / S2.11 rungs 1-3)."""

import functools

from flask import request

from errors import fail
from store import db

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

ROLES = (
    "PlatformAdmin",
    "Clerk",
    "FiscalOfficer",
    "Member",
    "Drafter",
    "ReviewCounsel",
    "AgencyAnalyst",
)

ALL_ROLES = ROLES


def authenticate():
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if not user_id or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED")
    return user_id, role


def endpoint(roles):
    """Rung 1 then rung 2, in that order, before the handler runs."""

    def decorator(handler):
        @functools.wraps(handler)
        def wrapper(**kwargs):
            user_id, role = authenticate()
            if role not in roles:
                fail("ERR_UNAUTHORIZED")
            return handler(user_id, role, **kwargs)

        return wrapper

    return decorator


def require_senior(user_id):
    """Rung 3: the backing Drafter row must exist and carry is_senior true."""
    drafter = db.drafters.get(user_id)
    if drafter is None or not drafter["is_senior"]:
        fail("ERR_SENIOR_COUNSEL_REQUIRED")
    return drafter
