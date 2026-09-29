"""Identity and authorisation — validation bands 1 and 2 of PRD §2.8.

`X-User-ID` and `X-User-Role` are checked before anything else, and the role is
checked before the body is parsed at all.
"""
from functools import wraps

from flask import g, request

from constants import ROLES
from errors import ApiError


def authorize(*roles):
    allowed = list(roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            # band 1 — identity headers present and non-empty
            if user_id is None or str(user_id).strip() == "":
                raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is missing or empty.")
            if role is None or str(role).strip() == "":
                raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is missing or empty.")
            role = role.strip()
            user_id = user_id.strip()
            # band 2 — a declared role that is authorised for this operation
            if role not in ROLES or role not in allowed:
                raise ApiError(
                    "ERR_ROLE_NOT_PERMITTED",
                    "Role {} may not perform this operation.".format(role),
                )
            g.user_id = user_id
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def actor():
    return g.get("user_id")


def role():
    return g.get("role")


def is_dealer_principal():
    return g.get("role") == "DealerPrincipal"
