"""PRD 2.1 - role based access control (validation ladder priorities 1-4, 8)."""
from functools import wraps

from flask import g, request

from core import ApiError

ANONYMOUS = "Anonymous"
COOK = "Cook"
DINER = "Diner"
COMPLIANCE_REVIEWER = "ComplianceReviewer"
SAFETY_OFFICER = "SafetyOfficer"
FINANCE_OPERATOR = "FinanceOperator"
PLATFORM_ADMIN = "PlatformAdmin"

ALL_ROLES = [
    ANONYMOUS,
    COOK,
    DINER,
    COMPLIANCE_REVIEWER,
    SAFETY_OFFICER,
    FINANCE_OPERATOR,
    PLATFORM_ADMIN,
]

# Roles for which X-User-ID is mandatory (PRD 2.1).
ID_BEARING_ROLES = {COOK, COMPLIANCE_REVIEWER, SAFETY_OFFICER, FINANCE_OPERATOR}

ROLE_HEADER = "X-User-Role"
USER_ID_HEADER = "X-User-ID"


def check_auth(allowed_roles):
    role = request.headers.get(ROLE_HEADER)
    if role is None or not role.strip():
        raise ApiError("ERR_MISSING_AUTH_HEADER")
    role = role.strip()
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNKNOWN_ROLE", "unknown role: %s" % role)

    user_id = request.headers.get(USER_ID_HEADER)
    user_id = user_id.strip() if isinstance(user_id, str) else None
    # Priority 3: applies to every endpoint whose authorised-role list includes
    # one of the four identity-bearing roles.
    if role in ID_BEARING_ROLES and ID_BEARING_ROLES.intersection(allowed_roles):
        if not user_id:
            raise ApiError("ERR_MISSING_USER_ID")

    if role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED", "role %s may not perform this operation" % role)

    g.role = role
    g.user_id = user_id or None
    return role, g.user_id


def guard(allowed_roles):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            check_auth(allowed_roles)
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def acting_role():
    return getattr(g, "role", None)


def acting_user():
    return getattr(g, "user_id", None)


def require_owner(cook_id):
    """Priority 8 - ERR_NOT_RESOURCE_OWNER. Only the Cook role is constrained;
    every other authorised role (including PlatformAdmin) passes through."""
    if acting_role() == COOK and acting_user() != cook_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
