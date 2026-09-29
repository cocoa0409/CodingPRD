"""Rejection-ladder steps 1 and 2 plus the per-request serialisation guard."""

import functools

from flask import g, request

from errors import ApiError
from store import ROLES, db


def actor():
    """(user_id, role) after ladder step 1 has passed."""
    return g.user_id, g.user_role


def _authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    if not role or not role.strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    g.user_id = user_id
    g.user_role = role


def _authorize(roles):
    if g.user_role not in roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")


def endpoint(blueprint, rule, methods, roles):
    """Register a handler behind the ladder's first two rungs.

    The whole handler runs under one re-entrant lock so cascades stay atomic,
    and ``g._mdl_touched`` gives ``store.touch`` its once-per-request
    version-bump semantics.
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with db.lock:
                g._mdl_touched = set()
                _authenticate()
                _authorize(roles)
                return func(*args, **kwargs)

        blueprint.add_url_rule(
            rule, endpoint=func.__name__, view_func=wrapper, methods=list(methods)
        )
        return wrapper

    return decorator
