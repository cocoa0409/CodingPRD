"""Auth header extraction and role checking per PRD §2.1."""

from flask import request

import db
from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_UNAUTHORIZED_ROLE,
)

DECLARED_ROLES = {
    "PlatformAdmin",
    "CustomerServiceRep",
    "Customer",
    "ProductionPlanner",
    "PressOperator",
    "QaInspector",
    "ProductionManager",
    "WarehouseManager",
    "BillingClerk",
}


def get_auth():
    """Extract and validate X-User-ID / X-User-Role. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in DECLARED_ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID or X-User-Role header missing, or role not declared",
            400,
        )
    return user_id, role


def require_role(role, allowed):
    """allowed: iterable of role names. 'Any' means any authenticated role."""
    allowed = set(allowed)
    if "Any" in allowed:
        return
    if role not in allowed:
        raise ApiError(
            ERR_UNAUTHORIZED_ROLE,
            "Authenticated role is not in the endpoint's permitted roles",
            403,
        )


def require_customer_ownership(user_id, role, release):
    """Entity-backed ownership: a Customer may act only on releases where
    release.customer_id == X-User-ID."""
    if role == "Customer":
        if release is None or release.get("customer_id") != user_id:
            raise ApiError(
                ERR_UNAUTHORIZED_ROLE,
                "Customer may act only on its own releases",
                403,
            )


def get_pagination():
    """Parse limit/offset query params with defaults limit=10 (min 1, max 100),
    offset=0. Invalid values -> ERR_INVALID_REQUEST."""
    from errors import ERR_INVALID_REQUEST

    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, "limit must be an integer", 400)
        if limit < 1 or limit > 100:
            raise ApiError(ERR_INVALID_REQUEST, "limit must be between 1 and 100", 400)
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, "offset must be an integer", 400)
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, "offset must be >= 0", 400)
    return limit, offset


def apply_pagination(items, limit, offset):
    """Sort by created_at ascending, then apply offset/limit."""
    items = sorted(items, key=lambda r: r["created_at"])
    total = len(items)
    return items[offset:offset + limit], total
