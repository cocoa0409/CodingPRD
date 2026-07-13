"""Authentication + RBAC (PRD Section 2.1 / SCAFFOLD roles)."""

from functools import wraps
from flask import request, g

from errors import ApiError

ALL_ROLES = ["CourtClerk", "Judge", "ProbationOfficer", "Cashier", "Defendant", "CourtAdmin"]


def endpoint(roles):
    """Decorator: enforce auth (401) then role authorization (403), in that order.

    Stashes the caller identity on flask.g for the handler to use.
    """
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or not role:
                raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role required")
            if role not in roles:
                raise ApiError("ERR_UNAUTHORIZED", "role not permitted for this operation")
            g.user_id = uid
            g.user_role = role
            return fn(*args, **kwargs)
        return wrapper
    return deco
