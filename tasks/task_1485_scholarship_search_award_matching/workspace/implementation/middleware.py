"""Auth middleware per PRD §2.1: X-User-ID + X-User-Role headers."""

from functools import wraps

from flask import request, g

from errors import raise_err

ROLES = {"Student", "ScholarshipCoordinator", "CommitteeReviewer",
         "FinancialAidOfficer", "Donor", "PlatformAdmin"}


def require_roles(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or not role or role not in ROLES:
                raise_err("ERR_UNAUTHENTICATED", "Missing or unknown X-User-Role / X-User-ID headers")
            if roles and role not in roles:
                raise_err("ERR_FORBIDDEN_ROLE", "Role not permitted for this endpoint")
            g.user_id = uid
            g.role = role
            return fn(*args, **kwargs)
        return wrapper
    return deco


def body():
    """Return the JSON request body as a dict (empty dict when absent)."""
    from flask import request as req
    data = req.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise_err("ERR_VALIDATION", "Request body must be a JSON object")
    return data
