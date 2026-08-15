"""Auth middleware (PRD §2.1): X-User-ID / X-User-Role headers, role gating.

Rung 1: both headers present and non-empty, else
ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (401).
Rung 2: role listed for the endpoint, else ERR_FORBIDDEN_ROLE (403).
"""
from functools import wraps

from flask import g, request

from errors import (
    raise_err,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_FORBIDDEN_ROLE,
)

ROLES = {
    "LabDirector",
    "SensoryScientist",
    "PanelCoordinator",
    "Panelist",
    "LabAnalyst",
    "QAOfficer",
    "Client",
}

ALL_ROLES = (
    "LabDirector",
    "SensoryScientist",
    "PanelCoordinator",
    "Panelist",
    "LabAnalyst",
    "QAOfficer",
    "Client",
)


def require_roles(*roles):
    allowed = set(roles) if roles else ROLES

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or not role:
                raise_err(
                    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                    "X-User-ID and X-User-Role headers must be present and "
                    "non-empty",
                )
            if role not in allowed:
                raise_err(
                    ERR_FORBIDDEN_ROLE,
                    f"Role {role} is not authorized for this endpoint",
                )
            g.user_id = uid
            g.user_role = role
            return fn(*args, **kwargs)

        return wrapper

    return deco
