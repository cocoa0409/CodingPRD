"""Auth header extraction, role checking, pagination, and body parsing helpers."""
from flask import request

from errors import (
    missing_context, forbidden, invalid_request, ApiError,
    ERR_INVALID_REQUEST,
)

ROLES = {"StateAgency", "McoEncounterOps", "McoCompliance", "McoFinance", "DelegatedSubmitter"}


def get_auth():
    """Stage 1: caller context. Returns (user_id, role) or raises."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise missing_context()
    if not role or role not in ROLES:
        raise missing_context()
    return user_id, role


def require_role(role, allowed):
    """Stage 2: authorization."""
    if role not in allowed:
        raise forbidden()


def get_body(required=True):
    """Parse JSON body. Returns dict (never None). Raises ERR_INVALID_REQUEST if malformed."""
    if request.content_length is None and not request.data:
        if required:
            raise invalid_request("Request body is required")
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise invalid_request("Request body is not valid JSON")
    if body is None:
        if required:
            raise invalid_request("Request body is required")
        return {}
    if not isinstance(body, dict):
        raise invalid_request("Request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise invalid_request(f"Missing required field: {f}")


def req_string(body, field):
    v = body.get(field)
    if not isinstance(v, str):
        raise invalid_request(f"Field {field} must be a string")
    return v


def req_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise invalid_request(f"Field {field} must be an integer")
    return v


def req_number(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise invalid_request(f"Field {field} must be a number")
    return v


def opt_string(body, field, default=None):
    v = body.get(field, default)
    if v is not None and not isinstance(v, str):
        raise invalid_request(f"Field {field} must be a string")
    return v


def opt_int(body, field, default=None):
    if field not in body:
        return default
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise invalid_request(f"Field {field} must be an integer")
    return v


def opt_number(body, field, default=None):
    if field not in body:
        return default
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise invalid_request(f"Field {field} must be a number")
    return v


def pagination_params():
    """Read limit/offset query params with defaults (limit=10, min 1, max 100, offset=0)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise invalid_request("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise invalid_request("offset must be an integer")
        if offset < 0:
            raise invalid_request("offset must be >= 0")
    return limit, offset


def apply_pagination(items):
    """Sort by created_at ascending, apply limit/offset. Returns (page, limit, offset, total)."""
    items = sorted(items, key=lambda x: (x.get("created_at", ""), x.get("id", "")))
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total
