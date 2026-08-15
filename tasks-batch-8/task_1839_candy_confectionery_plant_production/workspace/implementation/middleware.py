"""Auth header extraction, role checking, body/pagination/field helpers.

Auth (PRD §2.1): X-User-ID and X-User-Role headers are mandatory; the role
must name one of the five declared roles. Failures: ERR_UNAUTHENTICATED 401,
then ERR_UNAUTHORIZED_ROLE 403 when the role is not in the endpoint's list.
"""
from flask import request

from errors import ApiError

ROLES = ("ProductionPlanner", "PlantManager", "LineOperator", "SanitationLead", "QualityManager")
ALL_ROLES = ROLES
ALLERGEN_VOCAB = {"MILK", "SOY", "PEANUT", "TREE_NUT", "EGG", "WHEAT", "SESAME"}


def auth(allowed_roles):
    """Validate the auth headers and endpoint role list; return X-User-ID."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or unknown X-User-Role / X-User-ID headers.")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED_ROLE",
                       "The authenticated role is not listed among this endpoint's authorized roles.")
    return uid


def body():
    """Return the request JSON object; a missing body is treated as {} so the
    required-field checks report ERR_INVALID_REQUEST."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def require_fields(b, fields):
    for f in fields:
        if f not in b or b[f] is None:
            raise ApiError("ERR_INVALID_REQUEST", "Missing required field: %s" % f)


def paginate(items):
    """Envelope pagination: limit (default 10, min 1, max 100), offset
    (default 0). Returns (page_items, pagination_meta)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer.")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer.")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", "offset must be >= 0.")
    total = len(items)
    page = items[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
