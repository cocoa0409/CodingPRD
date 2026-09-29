"""Authentication / RBAC (validation rungs 1-3)."""
import functools

from flask import g, request

from errors import ApiError

ROLES = ("PlanningAdmin", "Allocator", "AllocationManager", "StoreOperator")


def require(*roles):
    """Rung 1: headers present and role recognised.  Rung 2: role authorised."""

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not role or role not in ROLES:
                raise ApiError("ERR_UNAUTHENTICATED")
            if role not in roles:
                raise ApiError("ERR_FORBIDDEN_ROLE")
            g.user_id = user_id
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return deco


def require_lenient(*roles):
    """Same as require(), but a call with no auth headers at all is allowed.

    Used only by the out-of-prefix test-driving clock endpoint, which carries no
    business data of its own; a supplied role is still checked against the list.
    """

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id and not role:
                g.user_id = "system"
                g.role = roles[0]
                return fn(*args, **kwargs)
            if not user_id or not role or role not in ROLES:
                raise ApiError("ERR_UNAUTHENTICATED")
            if role not in roles:
                raise ApiError("ERR_FORBIDDEN_ROLE")
            g.user_id = user_id
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return deco


def scope_check(owner_store_id):
    """Rung 3: a StoreOperator must act inside its own store."""
    if g.role == "StoreOperator" and g.user_id != owner_store_id:
        raise ApiError("ERR_STORE_SCOPE_VIOLATION")
