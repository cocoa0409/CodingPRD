"""Rule 1 (authentication) and rule 2 (role authorization) from PRD 2.4."""

from flask import request

import constants as K
from errors import ApiError


def actor():
    """Rule 1. Returns (user_id, role); raises ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in K.ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers.")
    return user_id, role


def require(role, allowed):
    """Rule 2. `allowed` is the endpoint's declared role list."""
    if role not in allowed:
        raise ApiError(
            "ERR_ROLE_NOT_PERMITTED",
            "Role %s may not perform this operation." % role,
        )


def begin(allowed):
    """Rules 1 + 2 in a single call."""
    user_id, role = actor()
    require(role, allowed)
    return user_id, role


def require_action_role(role, action, mapping):
    """Per-action role narrowing, evaluated at the rule-2 position.

    `mapping` maps an action name to the tuple of roles allowed to submit it.
    An unknown action is left alone so that rule 3 can report it.
    """
    if action is None:
        return
    allowed = mapping.get(action)
    if allowed is None:
        return
    if role not in allowed:
        raise ApiError(
            "ERR_ROLE_NOT_PERMITTED",
            "Role %s may not perform action %s." % (role, action),
        )
