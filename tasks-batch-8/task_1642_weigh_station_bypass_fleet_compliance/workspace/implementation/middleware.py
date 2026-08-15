"""Auth context, role admission, ownership, body validation, pagination.

Implements the PRD 2.10 validation ladder rungs 1-3 plus shared helpers for the
later rungs. Header scheme: X-User-ID + X-User-Role (PRD 2.1).
"""
from flask import request

from errors import ApiError
from response import ok_list
import db

ROLES = (
    "PlatformAdmin",
    "StateProgramManager",
    "ComplianceOfficer",
    "CarrierManager",
    "SafetyDataFeed",
    "TelematicsGateway",
    "FinanceAdmin",
)


def ctx():
    """Rung 1: user context headers present and role recognized."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            400,
            "X-User-ID and X-User-Role headers are required and X-User-Role must be a declared role",
        )
    return uid, role


def require_role(role, allowed, message=None):
    """Rung 2: role admission for the endpoint."""
    if role not in allowed:
        raise ApiError(
            "ERR_FORBIDDEN_ROLE",
            403,
            message or f"role {role} is not authorized for this operation",
        )


def ownership_guard(carrier_id, uid):
    """Rung 3: CarrierManager may act only on its own carrier's resources."""
    if carrier_id != uid:
        raise ApiError(
            "ERR_CARRIER_OWNERSHIP_MISMATCH",
            403,
            "CarrierManager identity does not match the carrier of the resource in scope",
        )


def body_json():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


# --- rung 12 field validators (raise ERR_INVALID_REQUEST) ---

def need_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or not v:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"{field} must be a non-empty string")
    return v


def need_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"{field} must be an integer")
    return v


def opt_int(body, field):
    v = body.get(field)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"{field} must be an integer")
    return v


def opt_bool(body, field, default):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"{field} must be a boolean")
    return v


def need_enum(body, field, values):
    v = body.get(field)
    if not isinstance(v, str) or v not in values:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, f"{field} must be one of {sorted(values)}"
        )
    return v


def pagination_args():
    """PRD 2.3: limit default 10, min 1, max 100; offset default 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be >= 0")
    return limit, offset


def list_response(records, filter_pairs):
    """Shared list handler: any authenticated role, exact-match filters,
    created_at ascending, limit/offset pagination (PRD 2.3)."""
    ctx()
    limit, offset = pagination_args()
    items = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    for param, key in filter_pairs:
        v = request.args.get(param)
        if v is not None:
            items = [r for r in items if str(r.get(key)) == v]
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([db.public(r) for r in page], limit, offset, total)
