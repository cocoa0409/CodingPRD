"""Auth middleware (SCAFFOLD validations priority 1-2 / PRD section 2.1).

Every request carries X-User-ID and X-User-Role. Roles: ComplianceOfficer,
EnrollmentSpecialist, PayerRepresentative, Provider. Missing headers or an
undeclared role -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400); a role not
authorized for the endpoint -> ERR_FORBIDDEN_FOR_ROLE (403).
"""
from functools import wraps

from flask import g, request

from errors import (
    ApiError,
    ERR_FORBIDDEN_FOR_ROLE,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
)

ALL_ROLES = ("ComplianceOfficer", "EnrollmentSpecialist", "PayerRepresentative", "Provider")


def require_roles(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or not role or role not in ALL_ROLES:
                raise ApiError(
                    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                    400,
                    "X-User-ID and X-User-Role headers are required and the role must be declared",
                )
            if role not in roles:
                raise ApiError(
                    ERR_FORBIDDEN_FOR_ROLE,
                    403,
                    "Role {} is not permitted for this endpoint".format(role),
                )
            g.user_id = uid
            g.user_role = role
            return fn(*args, **kwargs)

        return wrapper

    return deco
