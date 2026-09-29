"""Authentication, authorisation and caller identity (PRD 2.1, 2.10 steps 1-3)."""
import functools

from flask import g, request

import clock
import db
from errors import ApiError

ROLES = (
    "PavementEngineer",
    "BudgetOfficer",
    "UtilityCoordinator",
    "Inspector",
    "Contractor",
    "Resident",
)

ALL_ROLES = ROLES


def endpoint(*allowed_roles):
    """Run precedence steps 1-3 before handing control to the handler."""

    def decorator(handler):
        @functools.wraps(handler)
        def wrapper(*args, **kwargs):
            g.touched = set()
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not role or not role.strip():
                # PRD 2.1 names X-User-Role; tolerate the legacy X-Role alias.
                role = request.headers.get("X-Role")
            if not user_id or not user_id.strip():
                raise ApiError("ERR_UNAUTHENTICATED")
            if not role or not role.strip():
                raise ApiError("ERR_UNAUTHENTICATED")
            user_id = user_id.strip()
            role = role.strip()
            if role not in ROLES or role not in allowed_roles:
                raise ApiError("ERR_UNAUTHORIZED")
            g.user_id = user_id
            g.role = role
            if role == "Contractor" and user_id not in db.contractors:
                raise ApiError("ERR_UNKNOWN_CONTRACTOR_IDENTITY")
            return handler(*args, **kwargs)

        return wrapper

    return decorator


def touch(entity):
    """PRD 2.5: refresh updated_at and increment version, once per request."""
    if entity is None:
        return
    touched = getattr(g, "touched", None)
    if touched is None:
        touched = set()
        g.touched = touched
    key = id(entity)
    if key in touched:
        return
    touched.add(key)
    entity["updated_at"] = clock.now()
    entity["version"] = entity["version"] + 1
