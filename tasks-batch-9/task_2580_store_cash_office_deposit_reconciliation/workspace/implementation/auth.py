"""Header identity and role authorization (PRD sections 2.1 and 2.12 steps 1-2)."""
import functools

from flask import g, request

from errors import err

ROLES = (
    "Cashier",
    "CashOfficeClerk",
    "StoreManager",
    "ArmoredCarrier",
    "TreasuryAnalyst",
    "LossPreventionInvestigator",
)

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


def authenticate():
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or str(user_id).strip() == "":
        raise err("ERR_UNAUTHENTICATED", "%s header is required" % USER_ID_HEADER)
    if role is None or str(role).strip() == "":
        raise err("ERR_UNAUTHENTICATED", "%s header is required" % USER_ROLE_HEADER)
    role = role.strip()
    if role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "unknown role %r" % role)
    g.user_id = str(user_id).strip()
    g.role = role
    return g.user_id, g.role


def authorize(allowed_roles):
    if g.role not in allowed_roles:
        raise err("ERR_UNAUTHORIZED", "role %s may not perform this operation" % g.role)


def endpoint(roles):
    """Decorator applying step 1 (authentication) then step 2 (role authorization)."""

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            authenticate()
            authorize(roles)
            return view(*args, **kwargs)

        return wrapper

    return decorator


def user_id():
    return g.user_id


def role():
    return g.role


def is_cashier():
    return g.role == "Cashier"
