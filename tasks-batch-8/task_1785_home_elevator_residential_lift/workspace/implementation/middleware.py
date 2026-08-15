"""Auth context (PRD section 2.1): X-User-ID / X-User-Role headers.

Priority 1: headers present and role declared -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400).
Priority 2: role permitted on the endpoint -> ERR_FORBIDDEN (403).
"""

from functools import wraps

from flask import g, request

from errors import ApiError, ERR_FORBIDDEN, ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER

ALL_ROLES = [
    "DealerAdmin",
    "ProjectCoordinator",
    "Surveyor",
    "Installer",
    "Inspector",
    "Contractor",
    "Homeowner",
    "GrantOfficer",
    "Regulator",
]

DEALER_ADMIN = "DealerAdmin"
PROJECT_COORDINATOR = "ProjectCoordinator"
SURVEYOR = "Surveyor"
INSTALLER = "Installer"
INSPECTOR = "Inspector"
CONTRACTOR = "Contractor"
HOMEOWNER = "Homeowner"
GRANT_OFFICER = "GrantOfficer"
REGULATOR = "Regulator"


def require_roles(*roles):
    allowed = set(roles)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not role or role not in ALL_ROLES:
                raise ApiError(
                    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                    400,
                    "X-User-ID and X-User-Role headers are required and the role must be a declared role",
                )
            if allowed and role not in allowed:
                raise ApiError(ERR_FORBIDDEN, 403, f"Role {role} is not permitted on this endpoint")
            g.user_id = user_id
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return deco
