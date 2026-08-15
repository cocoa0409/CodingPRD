"""Auth / RBAC middleware and request-body validation helpers.

Pipeline order per PRD §2.6: user-context headers (400) -> role
authorization (403) -> existence (404) -> OCC (412) -> state gates (409)
-> business rules.
"""
from functools import wraps

from flask import g, request

from errors import (
    ApiError,
    ERR_FORBIDDEN_ROLE,
    ERR_INVALID_REQUEST,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
)
from money import dec
from timeutil import parse_iso

DECLARED_ROLES = {
    "ForwarderOps",
    "CapacityPlanner",
    "ComplianceOfficer",
    "CustomsBroker",
    "PricingManager",
    "ClaimsAdjuster",
}

ALL_ROLES = (
    "ForwarderOps",
    "CapacityPlanner",
    "ComplianceOfficer",
    "CustomsBroker",
    "PricingManager",
    "ClaimsAdjuster",
)


def require_roles(*roles):
    """Authenticate X-User-ID / X-User-Role, then authorize against roles."""

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or not role or role not in DECLARED_ROLES:
                raise ApiError(
                    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                    "X-User-ID and X-User-Role headers are required and the role must be a declared role.",
                    400,
                )
            if role not in roles:
                raise ApiError(
                    ERR_FORBIDDEN_ROLE,
                    f"Role {role} is not permitted for this operation.",
                    403,
                )
            g.user_id = uid
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return deco


def get_body():
    """Parse the JSON request body; malformed JSON or non-object -> 400."""
    if request.data is None or request.data == b"":
        return {}
    data = request.get_json(force=True, silent=True)
    if data is None or not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, "Request body must be a JSON object.", 400)
    return data


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(body, field):
    if field not in body or not isinstance(body[field], str):
        raise ApiError(ERR_INVALID_REQUEST, f"Field '{field}' is required and must be a string.", 400)
    return body[field]


def req_nonempty_str(body, field):
    v = req_str(body, field)
    if v == "":
        raise ApiError(ERR_INVALID_REQUEST, f"Field '{field}' must be non-empty.", 400)
    return v


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    if not isinstance(body[field], str):
        raise ApiError(ERR_INVALID_REQUEST, f"Field '{field}' must be a string.", 400)
    return body[field]


def req_int(body, field, minimum=None):
    if field not in body or not _is_int(body[field]):
        raise ApiError(ERR_INVALID_REQUEST, f"Field '{field}' is required and must be an integer.", 400)
    v = body[field]
    if minimum is not None and v < minimum:
        raise ApiError(ERR_INVALID_REQUEST, f"Field '{field}' must be >= {minimum}.", 400)
    return v


def opt_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    if not isinstance(body[field], bool):
        raise ApiError(ERR_INVALID_REQUEST, f"Field '{field}' must be a boolean.", 400)
    return body[field]


def req_num(body, field, minimum=None, exclusive_minimum=None):
    """Required JSON number -> Decimal."""
    if field not in body or body[field] is None:
        raise ApiError(ERR_INVALID_REQUEST, f"Field '{field}' is required and must be a number.", 400)
    try:
        v = dec(body[field])
    except Exception:
        raise ApiError(ERR_INVALID_REQUEST, f"Field '{field}' must be a number.", 400)
    if minimum is not None and v < dec(minimum):
        raise ApiError(ERR_INVALID_REQUEST, f"Field '{field}' must be >= {minimum}.", 400)
    if exclusive_minimum is not None and v <= dec(exclusive_minimum):
        raise ApiError(ERR_INVALID_REQUEST, f"Field '{field}' must be > {exclusive_minimum}.", 400)
    return v


def opt_num(body, field, default=None, minimum=None):
    if field not in body or body[field] is None:
        return default
    try:
        v = dec(body[field])
    except Exception:
        raise ApiError(ERR_INVALID_REQUEST, f"Field '{field}' must be a number.", 400)
    if minimum is not None and v < dec(minimum):
        raise ApiError(ERR_INVALID_REQUEST, f"Field '{field}' must be >= {minimum}.", 400)
    return v


def req_enum(body, field, allowed):
    v = req_str(body, field)
    if v not in allowed:
        raise ApiError(
            ERR_INVALID_REQUEST,
            f"Field '{field}' must be one of {sorted(allowed)}.",
            400,
        )
    return v


def req_datetime(body, field):
    if field not in body:
        raise ApiError(ERR_INVALID_REQUEST, f"Field '{field}' is required.", 400)
    try:
        return parse_iso(body[field])
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, f"Field '{field}' must be an ISO-8601 datetime.", 400)


def opt_version(body, field):
    """Optional OCC version field: accepts an integer or a numeric string.

    Returns None when absent, raises ERR_INVALID_REQUEST when unparseable.
    """
    if field not in body or body[field] is None:
        return None
    v = body[field]
    if _is_int(v):
        return v
    if isinstance(v, str):
        s = v.strip()
        if s.lstrip("-").isdigit():
            return int(s)
    raise ApiError(ERR_INVALID_REQUEST, f"Field '{field}' must be an integer.", 400)


def pagination_params():
    """limit: default 10, min 1, max 100; offset: default 0 (PRD §2.3)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, "Query parameter 'limit' must be an integer.", 400)
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, "Query parameter 'offset' must be an integer.", 400)
        if offset < 0:
            offset = 0
    return limit, offset
