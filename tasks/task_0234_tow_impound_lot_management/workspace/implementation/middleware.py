"""Auth header extraction (PRD §2.1) and request-body helpers."""
from flask import request

from errors import ApiError

VALID_ROLES = {"LotOperator", "PoliceOfficer", "TowProvider", "Claimant", "AuctionOfficial"}


def require_user_context():
    """Validate X-User-ID / X-User-Role headers (validation priority 1).
    Returns (user_id, role). Raises ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                       "X-User-ID header missing or malformed")
    if not role or role not in VALID_ROLES:
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                       "X-User-Role header missing or malformed")
    return user_id.strip(), role


def require_role(role, allowed):
    """RBAC check (validation priority 2)."""
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN_FOR_ROLE",
                       "Role %s is not permitted for this operation" % role)


def get_json_body():
    """Parse JSON body, tolerating an empty body as {}."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def get_query_int(name, default, minimum=None, maximum=None):
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return default
    if minimum is not None and val < minimum:
        val = minimum
    if maximum is not None and val > maximum:
        val = maximum
    return val
