"""Auth header extraction and RBAC (PRD 2.1, validation priorities 1-4)."""

import functools

from flask import g, request

from db import db
from errors import ApiError

ROLE_NAMES = (
    "CheckoutService",
    "RiskAnalyst",
    "ReviewLead",
    "PolicyEngineer",
    "PlatformAdmin",
)

# X-User-ID is resolved against the Analyst collection for these two roles only.
ENTITY_BACKED_ROLES = ("RiskAnalyst", "ReviewLead")


def roles(*allowed):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            role = request.headers.get("X-User-Role")
            if role is None or role.strip() == "":
                raise ApiError("ERR_MISSING_ROLE")
            if role not in ROLE_NAMES:
                raise ApiError("ERR_INVALID_ROLE")
            if role not in allowed:
                raise ApiError("ERR_UNAUTHORIZED")
            user_id = request.headers.get("X-User-ID")
            if role in ENTITY_BACKED_ROLES:
                if not user_id or user_id not in db.analysts:
                    raise ApiError("ERR_INVALID_USER_CONTEXT")
            g.role = role
            g.user_id = user_id
            return fn(*args, **kwargs)

        return wrapper

    return decorator
