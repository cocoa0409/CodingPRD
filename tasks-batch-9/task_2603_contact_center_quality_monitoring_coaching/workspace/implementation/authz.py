"""Authentication and role authorisation (PRD 2.1, ladder stages 1 and 2)."""
from functools import wraps

from flask import g, request

from common import fail

ROLES = ("QualityManager", "QualityEvaluator", "Agent", "Supervisor", "ComplianceAuditor")


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id == "" or role is None or role == "":
        fail("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role headers are required")
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role is not one of the five declared roles")
    g.user_id = user_id
    g.role = role


def endpoint(*roles):
    """Wrap a handler: stage 1 authentication then stage 2 authorisation."""

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            authenticate()
            if g.role not in roles:
                fail(
                    "ERR_UNAUTHORIZED",
                    "role %s is not authorised for this endpoint" % g.role,
                )
            return func(*args, **kwargs)

        return wrapper

    return decorator


def actor():
    return g.user_id


def actor_role():
    return g.role
