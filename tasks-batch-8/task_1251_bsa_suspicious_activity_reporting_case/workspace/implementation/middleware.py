"""Auth header extraction, role checking, body parsing (PRD section 2.1)."""
from flask import request

import db
from errors import ApiError

ROLES = {"ComplianceAdmin", "BSAAnalyst", "QAReviewer", "BSAManager"}
ENTITY_BACKED_ROLES = {"BSAAnalyst", "QAReviewer", "BSAManager"}
ALL_ROLES = ["ComplianceAdmin", "BSAAnalyst", "QAReviewer", "BSAManager"]


def get_body():
    """Parse the JSON request body; {} when absent. 400 on malformed JSON."""
    raw = request.data
    if not raw or not raw.strip():
        return {}
    data = request.get_json(silent=True, force=True)
    if data is None:
        raise ApiError("ERR_INVALID_REQUEST", "Malformed JSON body", 400)
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object", 400)
    return data


def authn():
    """Validate X-User-ID / X-User-Role. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise ApiError("ERR_UNAUTHENTICATED",
                       "X-User-ID and X-User-Role headers are required", 401)
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", f"Unrecognized role '{role}'", 401)
    if role in ENTITY_BACKED_ROLES and user_id not in db.analysts:
        raise ApiError("ERR_UNAUTHENTICATED",
                       "X-User-ID must reference an existing Analyst for this role", 401)
    return user_id, role


def authz(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN_ROLE",
                       f"Role '{role}' is not permitted on this endpoint", 403)


def pagination_params():
    """limit defaults 10 (min 1, max 100); offset defaults 0 (min 0). Values are clamped."""
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'limit' must be an integer", 400)
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'offset' must be an integer", 400)
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset
