"""Authentication, role authorization and ownership middleware.

Header scheme (per PRD section 2.1): X-User-ID + X-User-Role.
"""
from functools import wraps

from flask import request

from db import store
from errors import ApiError, raise_err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE

ROLES = {
    "IntakeWorker",
    "ProgramCoordinator",
    "QualityReviewer",
    "VolunteerCaller",
    "ExternalResponder",
}


def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise_err(ERR_UNAUTHENTICATED, "Missing or invalid X-User-Role / X-User-ID headers")
    return uid, role


def endpoint(roles):
    """Decorator: authenticates, authorizes role, then runs the handler under
    the global store lock. Injects uid and role kwargs."""

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid, role = authenticate()
            if role not in roles:
                raise_err(ERR_FORBIDDEN_ROLE, "Role %s is not authorized for this endpoint" % role)
            with store.lock:
                return fn(*args, uid=uid, role=role, **kwargs)

        return wrapper

    return deco


def get_body():
    """Parse JSON body; empty body -> {}. Non-JSON body -> None (caller 400s)."""
    raw = request.get_data()
    if raw is None or raw.strip() == b"":
        return {}
    import json

    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    return data
