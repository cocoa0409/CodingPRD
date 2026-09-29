"""Route registration helper.

Every request runs under a single process-wide lock so that cascades observe a
consistent store, and every handler receives the authenticated principal after
ladder steps 1-3 (PRD 2.8) have already been applied.
"""

import functools
import threading

from validation import authenticate

PREFIX = "/rv-marketplace"

_LOCK = threading.RLock()


def route(blueprint, rule, methods, roles):
    def decorator(handler):
        @functools.wraps(handler)
        def wrapper(**kwargs):
            with _LOCK:
                user_id, role = authenticate(roles)
                return handler(user_id, role, **kwargs)

        blueprint.add_url_rule(PREFIX + rule, handler.__name__, wrapper, methods=methods)
        return handler

    return decorator


def paged(items, limit, offset):
    return items[offset:offset + limit]
