"""Response envelope, error catalog, auth extraction, pagination, serialization."""
import random
import string
from datetime import datetime

from flask import jsonify, request

from store import render_dt, now, ROLES

# ---------------------------------------------------------------------------
# Error catalog: error_id -> HTTP status
# ---------------------------------------------------------------------------
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_ROLE_SCOPE_VIOLATION": 403,
    "ERR_NOT_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_VALIDATION": 400,
    "ERR_INVALID_PUNCH_INTERVAL": 400,
    "ERR_FACILITY_NOT_FOUND": 404,
    "ERR_CLINICIAN_NOT_FOUND": 404,
    "ERR_CREDENTIAL_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_SHIFT_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_TIMESHEET_NOT_FOUND": 404,
    "ERR_INVOICE_NOT_FOUND": 404,
    "ERR_RELIABILITY_EVENT_NOT_FOUND": 404,
    "ERR_CREDENTIAL_NOT_PENDING": 409,
    "ERR_ORDER_NOT_OPEN": 409,
    "ERR_SHIFT_NOT_OPEN": 409,
    "ERR_CLAIM_NOT_PENDING": 409,
    "ERR_ASSIGNMENT_NOT_CONFIRMED": 409,
    "ERR_ASSIGNMENT_NOT_CANCELLABLE": 409,
    "ERR_TIMESHEET_NOT_DISPUTABLE": 409,
    "ERR_TIMESHEET_NOT_VERIFIABLE": 409,
    "ERR_TIMESHEET_NOT_RESUBMITTABLE": 409,
    "ERR_INVOICE_NOT_DRAFT": 409,
    "ERR_INVOICE_NOT_ISSUED": 409,
    "ERR_INVOICE_NOT_VOIDABLE": 409,
    "ERR_EVENT_ALREADY_ADJUDICATED": 409,
    "ERR_CLINICIAN_SUSPENDED": 409,
    "ERR_STALE_SHIFT_VERSION": 412,
    "ERR_STALE_FACILITY_VERSION": 412,
    "ERR_CREDENTIAL_MISSING": 422,
    "ERR_CREDENTIAL_EXPIRED": 422,
    "ERR_CLAIM_WINDOW_CLOSED": 422,
    "ERR_SHIFT_NOT_ENDED": 422,
    "ERR_TIMESHEET_WINDOW_CLOSED": 422,
    "ERR_DUPLICATE_CLAIM": 409,
    "ERR_SHIFT_OVERLAP": 409,
    "ERR_REST_PERIOD_VIOLATION": 422,
    "ERR_UNIT_CAPACITY_EXCEEDED": 409,
    "ERR_HEADCOUNT_EXCEEDED": 422,
    "ERR_SHIFT_DURATION_INVALID": 422,
    "ERR_SHIFT_OUTSIDE_ORDER_WINDOW": 422,
    "ERR_WEEKLY_HOURS_EXCEEDED": 422,
    "ERR_CLAIM_LIMIT_EXCEEDED": 422,
    "ERR_RATE_CARD_NOT_FOUND": 422,
    "ERR_NO_ELIGIBLE_CLAIM": 409,
    "ERR_NO_BILLABLE_TIMESHEETS": 422,
    "ERR_INVOICE_PERIOD_OVERLAP": 409,
    "ERR_INVOICE_PERIOD_INVALID": 422,
    "ERR_DISPUTE_LIMIT_REACHED": 409,
    "ERR_PAYMENT_AMOUNT_MISMATCH": 422,
}


class AppError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP.get(error_id, 400)
        self.message = message or error_id


def _request_id():
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": render_dt(now()),
    }
    if extra:
        m.update(extra)
    return m


def _render_value(v):
    if isinstance(v, datetime):
        return render_dt(v)
    if isinstance(v, dict):
        return {k: _render_value(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_render_value(x) for x in v]
    return v


def serialize(entity):
    """Render an entity dict for output (datetimes -> ISO strings; drop internal keys)."""
    out = {}
    for k, v in entity.items():
        if k.startswith("_"):
            continue
        out[k] = _render_value(v)
    return out


def object_response(entity, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": serialize(entity) if entity is not None else {},
    }
    return jsonify(body), status


def raw_object_response(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": _render_value(data),
    }
    return jsonify(body), status


def array_response(items, limit, offset, total_count):
    has_more = offset + len(items) < total_count
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        }),
        "response_type": "array",
        "data": [serialize(i) for i in items],
    }
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def get_identity():
    """Return (user_id, role). Raises ERR_UNAUTHENTICATED if headers invalid."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise AppError("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers.")
    return user_id, role


def require(roles):
    """Authenticate and authorize the caller against an allowed role list."""
    user_id, role = get_identity()
    if role not in roles:
        raise AppError("ERR_UNAUTHORIZED", "Role not permitted on this endpoint.")
    return user_id, role


# ---------------------------------------------------------------------------
# Body / pagination helpers
# ---------------------------------------------------------------------------
def get_body():
    if request.data:
        try:
            data = request.get_json(force=True, silent=True)
        except Exception:
            data = None
    else:
        data = None
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise AppError("ERR_VALIDATION", "Request body must be a JSON object.")
    return data


def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        try:
            limit = int(args.get("limit"))
        except (TypeError, ValueError):
            limit = 10
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if "offset" in args:
        try:
            offset = int(args.get("offset"))
        except (TypeError, ValueError):
            offset = 0
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    window = items[offset:offset + limit]
    return window, total
