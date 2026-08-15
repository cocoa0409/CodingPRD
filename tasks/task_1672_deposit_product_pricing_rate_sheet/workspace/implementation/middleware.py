"""Auth header extraction and role checking (PRD section 2.1)."""

from functools import wraps

from flask import g, request

from errors import ApiError, ERR_FORBIDDEN_ROLE, ERR_UNAUTHENTICATED

ROLES = {
    "PricingAnalyst",
    "PricingCommittee",
    "TreasuryOfficer",
    "BranchBanker",
    "ComplianceOfficer",
    "ChannelOperator",
    "OperationsAdmin",
}


def get_body():
    """Return the JSON request body as a dict; {} when absent; 400 when malformed."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return data


def require_roles(*allowed):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not role or role not in ROLES:
                raise ApiError(ERR_UNAUTHENTICATED, 401,
                               "Missing or unknown X-User-Role / X-User-ID headers")
            if role not in allowed:
                raise ApiError(ERR_FORBIDDEN_ROLE, 403,
                               "Role not permitted for this endpoint")
            g.user_id = user_id
            g.user_role = role
            return fn(*args, **kwargs)
        return wrapper
    return deco


def parse_pagination():
    """Parse and validate limit/offset query params (PRD 2.3)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be an integer")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be between 1 and 100")
    if offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be >= 0")
    return limit, offset


def paginate(rows):
    """rows: full filtered list in creation order. Returns a paginated response."""
    limit, offset = parse_pagination()
    total = len(rows)
    page = rows[offset:offset + limit]
    from response import ok_list
    return ok_list(page, limit, offset, total)


def query_enum(name, allowed):
    """Optional enum query filter; invalid value -> 400. Returns value or None."""
    v = request.args.get(name)
    if v is None:
        return None
    if v not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"{name} must be one of {sorted(allowed)}")
    return v
