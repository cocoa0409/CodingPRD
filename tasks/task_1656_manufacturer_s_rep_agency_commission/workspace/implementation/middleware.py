"""Auth context extraction and role gating.

Headers: X-User-ID + X-User-Role. Roles: AgencyAdmin, Rep, PrincipalOps, Auditor.
Rep / PrincipalOps are entity-backed: X-User-ID must resolve to an existing
Rep / Principal record. AgencyAdmin / Auditor are opaque.
"""
from functools import wraps

from flask import request, g

import db
from errors import err

ROLES = ("AgencyAdmin", "Rep", "PrincipalOps", "Auditor")
ALL_ROLES = list(ROLES)


def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "X-User-ID and X-User-Role headers are required and must be valid")
    if role == "Rep" and uid not in db.reps:
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "X-User-ID does not resolve to an existing Rep")
    if role == "PrincipalOps" and uid not in db.principals:
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "X-User-ID does not resolve to an existing Principal")
    return {"user_id": uid, "role": role}


def api(roles):
    """Route decorator: authenticate, then enforce role membership."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            ctx = authenticate()
            if ctx["role"] not in roles:
                raise err("ERR_FORBIDDEN_FOR_ROLE",
                          "Role %s may not call this endpoint" % ctx["role"])
            g.ctx = ctx
            return fn(*args, **kwargs)
        return wrapper
    return deco


def ctx():
    return g.ctx


def body():
    """JSON request body as a dict; missing/invalid JSON yields {}."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}
