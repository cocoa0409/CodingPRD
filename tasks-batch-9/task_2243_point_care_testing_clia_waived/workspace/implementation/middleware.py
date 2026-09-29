"""Auth header extraction, role checking and the request dispatcher (PRD 2.1, 2.7)."""

import functools
import threading

from flask import request

import db
import errors

PREFIX = "/poct"

ROLES = ("ProgramAdmin", "LabDirector", "QualityCoordinator", "Operator", "Surveyor")

# LabDirector and Operator are entity-backed: X-User-ID must resolve to an
# Operator row.  ProgramAdmin, QualityCoordinator and Surveyor are opaque.
ENTITY_BACKED = ("LabDirector", "Operator")

# One process-wide lock so every cascade is observed atomically.
_LOCK = threading.RLock()


def authenticate(allowed_roles):
    # Rank 1 — authentication.
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise errors.unauthenticated()
    # Rank 2 — authorisation.
    if role not in allowed_roles:
        raise errors.unauthorized()
    if role in ENTITY_BACKED and db.get("operators", user_id) is None:
        raise errors.unauthorized()
    return user_id, role


def route(blueprint, rule, methods, roles):
    def decorator(handler):
        @functools.wraps(handler)
        def wrapper(**kwargs):
            with _LOCK:
                user_id, role = authenticate(roles)
                return handler(user_id, role, **kwargs)

        blueprint.add_url_rule(
            PREFIX + rule, handler.__name__, wrapper, methods=methods
        )
        return handler

    return decorator
