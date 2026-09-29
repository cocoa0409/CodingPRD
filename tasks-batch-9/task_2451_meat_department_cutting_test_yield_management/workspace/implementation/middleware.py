"""Auth-header extraction and role checking (PRD §2.1, ladder rungs 1, 2 and 6)."""

from flask import request

import errors
from errors import ApiError

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

STORE_ADMIN = "StoreAdmin"
MEAT_CUTTER = "MeatCutter"
MEAT_MANAGER = "MeatManager"
PRICING_ANALYST = "PricingAnalyst"
SERVICE_CLERK = "ServiceClerk"

ALL_ROLES = (STORE_ADMIN, MEAT_MANAGER, MEAT_CUTTER, PRICING_ANALYST, SERVICE_CLERK)
NO_SERVICE_CLERK = (STORE_ADMIN, MEAT_MANAGER, MEAT_CUTTER, PRICING_ANALYST)
ADMIN_MANAGER_CUTTER = (STORE_ADMIN, MEAT_MANAGER, MEAT_CUTTER)
COLD_CHAIN_READERS = (STORE_ADMIN, MEAT_MANAGER, MEAT_CUTTER, SERVICE_CLERK)
RECONCILIATION_READERS = (STORE_ADMIN, MEAT_MANAGER, PRICING_ANALYST)


def authenticate(allowed_roles):
    """Rung 1 then rung 2. Returns ``(user_id, role)``."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or role is None or user_id == "" or role == "":
        raise ApiError(
            errors.ERR_UNAUTHENTICATED, 401,
            "Both X-User-ID and X-User-Role headers are required",
        )
    if role not in allowed_roles:
        raise ApiError(
            errors.ERR_ROLE_NOT_PERMITTED, 403,
            "Role %s is not authorized for this endpoint" % role,
        )
    return user_id, role


def check_action_role(role, action, action_roles):
    """Rung 6 — per-action ownership (PRD §2.1)."""
    allowed = action_roles.get(action, ())
    if role not in allowed:
        raise ApiError(
            errors.ERR_TRANSITION_ROLE_NOT_PERMITTED, 403,
            "Role %s may not request action %s" % (role, action),
        )
