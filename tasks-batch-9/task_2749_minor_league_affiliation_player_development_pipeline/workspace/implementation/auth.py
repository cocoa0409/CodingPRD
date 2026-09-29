"""Auth header extraction and the role / scope / action gates (checks 1-6)."""
from flask import request

import config
from errors import ApiError


def identity():
    user_id = request.headers.get(config.HEADER_USER_ID)
    role = request.headers.get(config.HEADER_USER_ROLE)
    if user_id is None or not user_id.strip() or role is None or not role.strip():
        raise ApiError("ERR_MISSING_AUTH_HEADERS")
    if role not in config.ALL_ROLES:
        raise ApiError("ERR_INVALID_ROLE")
    return user_id, role


def require(*allowed_roles):
    """Checks 1, 2 and 3 in a single call."""
    user_id, role = identity()
    if role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    return user_id, role


def raw_body():
    """Body as a dict for the pre-check-8 reads (action lookup); never raises."""
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    return {}


def check_scope(role, user_id, affiliate_id):
    """Check 4: an AffiliateOperator may only touch its own affiliate."""
    if role == config.ROLE_OPERATOR and affiliate_id is not None:
        if user_id != affiliate_id:
            raise ApiError("ERR_AFFILIATE_SCOPE_VIOLATION")


def check_action_role(action, role, table):
    """Check 5: the requested action must be one this role may request.

    An absent or unrecognized action is left to check 8 (ERR_INVALID_REQUEST).
    """
    if isinstance(action, str) and action in table:
        if role not in table[action]:
            raise ApiError("ERR_ROLE_NOT_PERMITTED")


def require_action(body, table):
    """Check 8 for the action field itself."""
    action = body.get("action")
    if not isinstance(action, str) or action not in table:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field 'action' must be one of %s." % ", ".join(sorted(table)))
    return action
