from flask import request

from errors import (
    raise_err,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_ROLE_FORBIDDEN,
)


VALID_ROLES = {"Seller", "Bidder", "ArbitratorOps", "PlatformAdmin", "Anonymous"}


def get_user_context():
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if not user_id or not user_role:
        raise_err(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
    if user_role not in VALID_ROLES:
        raise_err(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
    return user_id, user_role


def require_role(allowed_roles):
    user_id, user_role = get_user_context()
    if user_role not in allowed_roles:
        raise_err(ERR_ROLE_FORBIDDEN)
    return user_id, user_role
