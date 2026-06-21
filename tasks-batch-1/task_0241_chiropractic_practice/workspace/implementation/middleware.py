"""Auth, RBAC, pagination, and shared helpers (PRD §2.1, §2.3, §2.6)."""
from flask import request

from errors import err

KNOWN_ROLES = {"Provider", "FrontDesk", "BillingClerk", "PracticeAdmin"}


def authenticate():
    """PRD §2.1: X-User-ID and X-User-Role required; role must be known.

    Returns (user_id, role). Raises ERR_UNAUTHENTICATED otherwise.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers")
    return user_id, role


def authorize(role, allowed_roles):
    """PRD §2.1: ERR_FORBIDDEN_ROLE when role not permitted for the operation."""
    if role not in allowed_roles:
        raise err("ERR_FORBIDDEN_ROLE", "Role %s is not permitted for this operation" % role)


def get_json_body():
    """Parse JSON body; treat missing body as empty object."""
    if request.data and len(request.data) > 0:
        try:
            body = request.get_json(force=True, silent=True)
        except Exception:
            raise err("ERR_INVALID_REQUEST", "Malformed JSON body")
        if body is None:
            raise err("ERR_INVALID_REQUEST", "Malformed JSON body")
        if not isinstance(body, dict):
            raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
        return body
    return {}


def parse_pagination():
    """PRD §2.3: limit default 10 (min 1, max 100); offset default 0 (no upper bound).

    Out-of-range / malformed pagination params are rejected as ERR_INVALID_REQUEST.
    """
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0")

    return limit, offset


def paginate(items):
    """Sort by creation order, slice by limit/offset, build pagination meta."""
    limit, offset = parse_pagination()
    ordered = sorted(items, key=lambda r: r.get("_seq", 0))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    has_more = offset + limit < total
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
    return window, pagination
