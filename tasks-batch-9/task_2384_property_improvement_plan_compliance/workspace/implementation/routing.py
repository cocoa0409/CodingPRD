"""Tiny route registry so route modules can be declared independently."""

import threading
from functools import wraps

from flask import g

from middleware import authenticate

ROUTES = []

_lock = threading.RLock()


def route(rule, methods, roles):
    def decorator(fn):
        ROUTES.append((rule, tuple(methods), roles, fn))
        return fn

    return decorator


def make_view(fn, roles):
    @wraps(fn)
    def view(**kwargs):
        with _lock:
            user_id, role = authenticate(roles)
            g.user_id = user_id
            g.role = role
            return fn(**kwargs)

    return view
