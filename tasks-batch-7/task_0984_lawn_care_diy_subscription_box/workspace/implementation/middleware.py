from flask import request

from errors import (
    raise_err,
    ERR_MISSING_HEADERS,
    ERR_FORBIDDEN_ROLE,
    ERR_OWNERSHIP_MISMATCH,
    ERR_INVALID_REQUEST,
)

ROLES = {"Anonymous", "Customer", "Agronomist", "FulfillmentOps", "PlatformAdmin"}


def get_body(required=True):
    """Return the JSON request body as a dict; {} when absent and optional."""
    body = request.get_json(silent=True)
    if body is None:
        if required:
            raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
        return {}
    if not isinstance(body, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def authenticate(allowed_roles):
    """Priority 1 then 2: header context, then role permission.

    Returns (user_id, role).
    """
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or role is None:
        raise_err(ERR_MISSING_HEADERS, "X-User-ID and X-User-Role headers are required")
    uid = uid.strip()
    role = role.strip()
    if not uid or role not in ROLES:
        raise_err(ERR_MISSING_HEADERS, "X-User-ID or X-User-Role header is malformed")
    if role not in allowed_roles:
        raise_err(ERR_FORBIDDEN_ROLE, "Role %s is not permitted for this operation" % role)
    return uid, role


def check_ownership(uid, role, owner_customer_id):
    """Priority 3: entity-backed ownership for the Customer role."""
    if role == "Customer" and uid != owner_customer_id:
        raise_err(ERR_OWNERSHIP_MISMATCH, "Acting customer does not own the target resource")


def paginate(items):
    """limit/offset per PRD 2.3: default 10, min 1, max 100, offset default 0.

    `items` must already be filtered and sorted; returns (page, total, limit, offset).
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "Query parameter 'limit' must be an integer")
        limit = max(1, min(100, limit))
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "Query parameter 'offset' must be an integer")
        offset = max(0, offset)
    total = len(items)
    return items[offset:offset + limit], total, limit, offset


def sort_items(items):
    """List responses sort by created_at ascending; seq breaks same-instant ties
    in insertion order."""
    return sorted(items, key=lambda r: (r.created_at, r.seq))
