from flask import request

import errors
from errors import err

ROLES = {"NCA_Admin", "EligibilityOfficer", "SchedulingClerk", "MarkerClerk", "HonorsCoordinator"}
ALL_ROLES = ROLES


def require_auth():
    """Validate X-User-ID and X-User-Role are present and role is recognized.

    Returns (user_id, role). Raises ERR_UNAUTHENTICATED on missing headers.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err(errors.ERR_UNAUTHENTICATED, "Missing or invalid authentication headers")
    return user_id, role


def require_roles(role, allowed):
    if role not in allowed:
        raise err(errors.ERR_UNAUTHORIZED, "Role not permitted for this operation")


def pagination_params():
    """Parse and validate limit/offset. Raises ERR_VALIDATION on bad values."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err(errors.ERR_VALIDATION, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err(errors.ERR_VALIDATION, "limit out of range")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err(errors.ERR_VALIDATION, "offset must be an integer")
        if offset < 0:
            raise err(errors.ERR_VALIDATION, "offset must be >= 0")
    return limit, offset


def paginate(items):
    """Sort by creation sequence ascending, apply limit/offset."""
    limit, offset = pagination_params()
    ordered = sorted(items, key=lambda r: r["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, limit, offset, total
