"""Auth: X-User-ID / X-User-Role extraction and role gating (PRD section 2.1).

Validation priority: header presence/role validity (p1, 400) runs before the
per-operation role permission check (p2, 403), which runs before existence.
"""
from functools import wraps

from flask import request

from errors import err, ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, ERR_FORBIDDEN_ROLE

ROLES = {
    "RadiationOncologist",
    "MedicalDosimetrist",
    "MedicalPhysicist",
    "RadiationTherapist",
    "Scheduler",
    "BillingCoordinator",
    "SystemAdmin",
}

ALL_ROLES = tuple(sorted(ROLES))


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        err(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers are required and the role must be one of the seven declared roles")
    return user_id, role


def require_roles(*allowed):
    """Decorator: authenticates (p1) then enforces role permission (p2)."""

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = authenticate()
            if role not in allowed:
                err(ERR_FORBIDDEN_ROLE, "Role lacks permission for this operation")
            return fn(*args, user_id=user_id, **kwargs)

        return wrapper

    return deco


def get_body():
    """JSON request body as a dict; missing/invalid body counts as empty so
    required-field schema validation produces ERR_INVALID_REQUEST."""
    from flask import request as _req

    data = _req.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        err(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return data
