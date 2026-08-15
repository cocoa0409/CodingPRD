"""Shared request utilities: auth headers, RBAC, body validation, pagination."""
from flask import request

import clock
import db
from errors import ApiError, err_missing_user_context, err_insufficient_permissions, err_invalid_request

ROLES = [
    "OperationsManager", "Captain", "Customer",
    "CharterSalesAgent", "GalleyManager", "DockAttendant",
]

DEFAULT_LIMIT = 10
MAX_LIMIT = 100
MIN_LIMIT = 1


def require_auth(allowed_roles):
    """Validation ladder rungs 1-2: header presence/well-formedness, then role."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or not role or role not in ROLES:
        raise err_missing_user_context()
    if role not in allowed_roles:
        raise err_insufficient_permissions()
    return uid, role


def get_json(required_fields=(), optional_fields=()):
    """Request-shape validation: malformed JSON, unknown field, missing required
    field, null required field are all ERR_INVALID_REQUEST. An entirely absent
    body on a no-input action is tolerated as an empty object."""
    raw = request.get_data()
    if not raw or not raw.strip():
        body = {}
    else:
        body = request.get_json(silent=True)
        if body is None:
            raise err_invalid_request("Malformed JSON body")
    if not isinstance(body, dict):
        raise err_invalid_request("Malformed JSON body")
    allowed = set(required_fields) | set(optional_fields)
    for key in body:
        if key not in allowed:
            raise err_invalid_request(f"Unexpected field: {key}")
    for field in required_fields:
        if field not in body or body[field] is None:
            raise err_invalid_request(f"Missing required field: {field}")
    return body


def paginate(items):
    """limit/offset per PRD section 2.3; invalid values are ERR_INVALID_REQUEST."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err_invalid_request("limit must be an integer")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise err_invalid_request("limit out of range")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err_invalid_request("offset must be an integer")
        if offset < 0:
            raise err_invalid_request("offset out of range")
    total = len(items)
    page = items[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }


def get_or_404(store, resource_id, error_key, message):
    rec = store.get(resource_id)
    if rec is None:
        from errors import NOT_FOUND_IDS, err_not_found
        raise err_not_found(NOT_FOUND_IDS[error_key], message)
    return rec


def touch(record, with_version=True):
    """Refresh updated_at and bump version (common-fields resources only)."""
    record["updated_at"] = clock.to_z(clock.now())
    if with_version:
        record["version"] = record.get("version", 1) + 1


def check_enum(body, field, allowed):
    value = body.get(field)
    if value not in allowed:
        raise err_invalid_request(f"Invalid value for {field}")
    return value


def check_int(body, field, minimum=None):
    value = body.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise err_invalid_request(f"{field} must be an integer")
    if minimum is not None and value < minimum:
        raise err_invalid_request(f"{field} must be >= {minimum}")
    return value


def check_number(body, field):
    value = body.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise err_invalid_request(f"{field} must be a number")
    return value


def check_str(body, field):
    value = body.get(field)
    if not isinstance(value, str):
        raise err_invalid_request(f"{field} must be a string")
    return value


def check_datetime(body, field):
    value = body.get(field)
    dt = clock.parse_dt(value)
    if dt is None:
        raise err_invalid_request(f"{field} must be an ISO-8601 datetime")
    return dt
