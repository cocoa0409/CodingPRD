"""Authentication and role authorisation (PRD 2.1, screening steps 1-2)."""

from flask import request

import errors
from errors import ApiError

ROLES = ("PlatformAdmin", "AssetManager", "MarketTrader", "MarketOperator",
         "ControlRoomOperator", "SiteController", "SafetyOfficer")

USER_HEADER = "X-User-ID"
ROLE_HEADER = "X-User-Role"

SYSTEM_ACTOR = "SYSTEM"


def identity():
    """Step 1 — both headers present, non-empty, role recognised."""
    user_id = request.headers.get(USER_HEADER)
    role = request.headers.get(ROLE_HEADER)
    if user_id is None or str(user_id).strip() == "":
        raise ApiError(errors.ERR_UNAUTHENTICATED, 401,
                       "X-User-ID header is required")
    if role is None or str(role).strip() == "":
        raise ApiError(errors.ERR_UNAUTHENTICATED, 401,
                       "X-User-Role header is required")
    if role not in ROLES:
        raise ApiError(errors.ERR_UNAUTHENTICATED, 401,
                       "X-User-Role is not a recognised role")
    return user_id, role


def authorize(*allowed):
    """Steps 1 then 2.  No arguments (or the sentinel "*") means every
    authenticated role may act — all seven roles may read everything."""
    user_id, role = identity()
    if allowed and "*" not in allowed and role not in allowed:
        raise ApiError(errors.ERR_FORBIDDEN_ROLE, 403,
                       "Role %s may not perform this operation" % role)
    return user_id, role


def any_role():
    return authorize()


def check_asset_ownership(user_id, role, asset_id):
    """Step 7 — a SiteController acts only for the asset that is its own id."""
    if role == "SiteController" and user_id != asset_id:
        raise ApiError(errors.ERR_ASSET_OWNERSHIP_MISMATCH, 403,
                       "SiteController may only act for its own asset")
