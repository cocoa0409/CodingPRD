"""Auth header extraction, role gating and per-request mutation bookkeeping."""

from functools import wraps

from flask import g, request

from db import LOCK
from errors import fail
from services import tracking
from services.calc import ROLES

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


def _identity():
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or not str(user_id).strip() or role is None or not str(role).strip():
        fail("ERR_UNAUTHENTICATED")
    return str(user_id).strip(), str(role).strip()


def endpoint(roles=None, mutating=False, authenticated=True):
    """Priority 1 (auth) and priority 2 (role) run before anything else."""
    def decorator(fn):
        @wraps(fn)
        def inner(*args, **kwargs):
            if authenticated:
                user_id, role = _identity()
                if role not in ROLES:
                    fail("ERR_ROLE_NOT_PERMITTED")
                if roles is not None and role not in roles:
                    fail("ERR_ROLE_NOT_PERMITTED")
                g.user_id = user_id
                g.role = role
            else:
                g.user_id = None
                g.role = None
            if not mutating:
                with LOCK:
                    tracking.begin()
                    return fn(*args, **kwargs)
            with LOCK:
                before = tracking.snapshot()
                tracking.begin()
                g.tracked = set(before.keys())
                result = fn(*args, **kwargs)
                tracking.settle(before)
                return result
        return inner
    return decorator


def is_generator():
    return getattr(g, "role", None) == "Generator"


def caller_id():
    return getattr(g, "user_id", None)
