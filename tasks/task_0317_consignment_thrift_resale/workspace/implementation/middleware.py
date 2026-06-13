"""Auth header extraction and role checking (PRD §2.1)."""
from functools import wraps

from flask import request

from errors import err

VALID_ROLES = {
    "StoreAdmin",
    "IntakeGrader",
    "Authenticator",
    "CashierClerk",
    "SettlementManager",
}


def get_identity():
    """Return (user_id, role) from the request headers, validating presence.

    Raises ERR_UNAUTHENTICATED if either header is missing/blank or the role is
    not one of the five recognized roles.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err("ERR_UNAUTHENTICATED", "Missing X-User-ID or X-User-Role header")
    if role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Unrecognized X-User-Role")
    return user_id, role


def require(*allowed_roles):
    """Decorator: enforce authentication then role membership.

    Auth (ERR_UNAUTHENTICATED) is checked before role (ERR_FORBIDDEN_ROLE),
    matching the validation precedence in PRD §2.5.
    """
    allowed = set(allowed_roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_identity()
            if role not in allowed:
                raise err(
                    "ERR_FORBIDDEN_ROLE",
                    "Role %s not permitted for this operation" % role,
                )
            request.user_id = user_id
            request.user_role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator
