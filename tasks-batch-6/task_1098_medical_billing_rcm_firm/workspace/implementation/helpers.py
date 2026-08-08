"""Response envelope, error type, request context, auth, pagination."""
import random
import string

from flask import jsonify, request, g

import store

# ---------------------------------------------------------------------------
# Roles (§2.1) — spelled exactly.
# ---------------------------------------------------------------------------
ROLES = {
    "AccountManager", "Coder", "Biller", "DenialSpecialist",
    "PaymentPoster", "CredentialingSpecialist", "PracticeUser",
}


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------
def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": store.render_dt(store.clock_now()),
    }
    if extra:
        m.update(extra)
    return m


def success(data, status=200, list_meta=None):
    response_type = "array" if isinstance(data, list) else "object"
    body = {
        "meta": _meta(list_meta),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Auth (§2.1) — validations priority 1 (401) and 2 (403).
# ---------------------------------------------------------------------------
def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or malformed authentication headers")
    g.user_id = user_id
    g.role = role
    return user_id, role


def require_roles(*allowed):
    if g.role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")


def practice_user_can_read(practice_id):
    """PracticeUser ownership check: X-User-ID must equal the practice id the
    resource belongs to. Non-owner PracticeUser -> ERR_UNAUTHORIZED (403)."""
    if g.role == "PracticeUser" and g.user_id != practice_id:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Practice user may only read its own practice's resources")


# ---------------------------------------------------------------------------
# Body / field validation helpers
# ---------------------------------------------------------------------------
def get_body():
    if request.data and len(request.data) > 0:
        try:
            body = request.get_json(force=True, silent=True)
        except Exception:
            body = None
    else:
        body = None
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", 422, "Request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise ApiError("ERR_VALIDATION", 422, "Missing required field: %s" % f)


def require_string(body, field, required=True):
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_VALIDATION", 422, "Missing required field: %s" % field)
        return None
    v = body[field]
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", 422, "Field %s must be a non-empty string" % field)
    return v


def require_int(body, field, required=True, min_value=None, money=False):
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_VALIDATION", 422, "Missing required field: %s" % field)
        return None
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", 422, "Field %s must be an integer" % field)
    if money and v < 0:
        raise ApiError("ERR_NEGATIVE_AMOUNT", 422, "Field %s must not be negative" % field)
    if min_value is not None and v < min_value:
        raise ApiError("ERR_VALIDATION", 422, "Field %s below minimum" % field)
    return v


def require_number(body, field, required=True, lo=None, hi=None, lo_strict=False, hi_strict=False):
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_VALIDATION", 422, "Missing required field: %s" % field)
        return None
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_VALIDATION", 422, "Field %s must be a number" % field)
    if lo is not None:
        if lo_strict and not (v > lo):
            raise ApiError("ERR_VALIDATION", 422, "Field %s out of range" % field)
        if not lo_strict and not (v >= lo):
            raise ApiError("ERR_VALIDATION", 422, "Field %s out of range" % field)
    if hi is not None:
        if hi_strict and not (v < hi):
            raise ApiError("ERR_VALIDATION", 422, "Field %s out of range" % field)
        if not hi_strict and not (v <= hi):
            raise ApiError("ERR_VALIDATION", 422, "Field %s out of range" % field)
    return v


def require_enum(body, field, allowed, required=True):
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_VALIDATION", 422, "Missing required field: %s" % field)
        return None
    v = body[field]
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", 422, "Field %s must be a string" % field)
    if v not in allowed:
        raise ApiError("ERR_INVALID_ENUM", 422, "Field %s carries an invalid value" % field)
    return v


def require_datetime(body, field, required=True):
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_VALIDATION", 422, "Missing required field: %s" % field)
        return None
    v = body[field]
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", 422, "Field %s must be an ISO-8601 string" % field)
    try:
        return store.parse_dt(v)
    except Exception:
        raise ApiError("ERR_VALIDATION", 422, "Field %s is not a valid timestamp" % field)


# ---------------------------------------------------------------------------
# Pagination (§2.3)
# ---------------------------------------------------------------------------
def parse_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 422, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_VALIDATION", 422, "limit out of bounds")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 422, "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", 422, "offset out of bounds")
    return limit, offset


def paginate(items, serializer):
    """Sort by created_at ascending, slice, and build the list envelope meta."""
    limit, offset = parse_pagination()
    ordered = sorted(items, key=lambda r: (r["created_at"], r["id"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    data = [serializer(r) for r in page]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return success(data, 200, list_meta=meta)
