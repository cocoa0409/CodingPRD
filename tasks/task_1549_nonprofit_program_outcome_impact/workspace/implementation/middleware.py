"""Auth middleware: header extraction, role validation, RBAC enforcement.

Validation priorities 1-3 (SCAFFOLD 1.4):
  1. X-User-Role and X-User-ID headers present -> ERR_MISSING_AUTH_HEADERS (401)
  2. X-User-Role value is a declared role name -> ERR_UNKNOWN_ROLE (401)
  3. acting role is listed in the endpoint's roles -> ERR_UNAUTHORIZED_ROLE (403)
"""
from functools import wraps

from flask import g, request

from errors import ApiError

ROLES = {
    "ProgramDirector",
    "EvaluationLead",
    "FieldCollector",
    "DataSteward",
    "PrivacyOfficer",
    "FunderViewer",
    "VendorAnalyst",
}


def require_roles(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if uid is None or uid == "" or role is None or role == "":
                raise ApiError(
                    "ERR_MISSING_AUTH_HEADERS",
                    401,
                    "X-User-ID and X-User-Role headers are required.",
                )
            if role not in ROLES:
                raise ApiError("ERR_UNKNOWN_ROLE", 401, f"Unknown role: {role}")
            if role not in roles:
                raise ApiError(
                    "ERR_UNAUTHORIZED_ROLE",
                    403,
                    f"Role {role} is not authorized for this endpoint.",
                )
            g.user_id = uid
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return deco
