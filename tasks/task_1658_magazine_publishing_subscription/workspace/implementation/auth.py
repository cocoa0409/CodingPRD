"""Auth middleware: X-User-ID / X-User-Role headers and role gating.

Priority 1: both headers must be present and the role must be one of the five
recognized roles, else ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400).
Priority 2: the role must be authorized for the endpoint, else
ERR_INSUFFICIENT_PERMISSIONS (403).
"""

import functools

from flask import request

from errors import err

VALID_ROLES = {
    "PublishingDirector",
    "ProductionManager",
    "CirculationManager",
    "FulfillmentManager",
    "PostalComplianceOfficer",
}

ALL_ROLES = sorted(VALID_ROLES)


def current_role():
    return request.headers.get("X-User-Role")


def require_roles(allowed):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not role or role not in VALID_ROLES:
                raise err(
                    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                    "X-User-ID and X-User-Role headers must be present and valid",
                )
            if role not in allowed:
                raise err(
                    "ERR_INSUFFICIENT_PERMISSIONS",
                    f"Role {role} is not permitted to perform this operation",
                )
            return fn(*args, **kwargs)

        return wrapper

    return decorator
