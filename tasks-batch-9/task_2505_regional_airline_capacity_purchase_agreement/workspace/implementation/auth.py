"""Authentication and role authorisation (PRD 2.1, rejection precedence 1-2)."""

import functools

from flask import g, request

from errors import fail

ROLE_CPA_ADMINISTRATOR = "CPAAdministrator"
ROLE_MAINLINE_SCHEDULER = "MainlineScheduler"
ROLE_REGIONAL_OPS_CONTROLLER = "RegionalOpsController"
ROLE_BASE_CHIEF_PILOT = "BaseChiefPilot"
ROLE_BRAND_AUDITOR = "BrandAuditor"

ALL_ROLES = (
    ROLE_CPA_ADMINISTRATOR,
    ROLE_MAINLINE_SCHEDULER,
    ROLE_REGIONAL_OPS_CONTROLLER,
    ROLE_BASE_CHIEF_PILOT,
    ROLE_BRAND_AUDITOR,
)

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


def authenticate():
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or role is None:
        fail("ERR_UNAUTHENTICATED")
    if user_id.strip() == "" or role.strip() == "":
        fail("ERR_UNAUTHENTICATED")
    if role not in ALL_ROLES:
        fail("ERR_UNAUTHENTICATED")
    g.user_id = user_id
    g.user_role = role
    return user_id, role


def require(*roles):
    """Authenticate, then enforce the endpoint's role list."""
    allowed = roles if roles else ALL_ROLES

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            _, role = authenticate()
            if role not in allowed:
                fail("ERR_FORBIDDEN_ROLE")
            return view(*args, **kwargs)

        return wrapper

    return decorator


def any_role():
    return require(*ALL_ROLES)


def current_user_id():
    return getattr(g, "user_id", None)


def current_role():
    return getattr(g, "user_role", None)
