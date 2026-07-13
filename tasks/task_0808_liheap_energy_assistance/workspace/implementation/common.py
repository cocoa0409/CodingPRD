"""Response envelope, error type, auth/identity, and body-validation helpers."""
import random
import string
from functools import wraps

from flask import request, jsonify

from store import wall_iso

# --------------------------------------------------------------------------
# Error catalogue (id -> http status). §1.6 / PRD §5.
# --------------------------------------------------------------------------
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_VALIDATION": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_APPLICATION_NOT_APPROVED": 409,
    "ERR_INVALID_REFERENCE": 422,
    "ERR_POOL_COMPONENT_MISMATCH": 422,
    "ERR_SEASON_CLOSED": 409,
    "ERR_CRISIS_DEADLINE_PASSED": 409,
    "ERR_CRISIS_NOT_DUE": 409,
    "ERR_DUPLICATE_APPLICATION": 409,
    "ERR_INCOME_INELIGIBLE": 422,
    "ERR_INCOME_NOT_VERIFIED": 409,
    "ERR_CRISIS_WINDOW_OVERLAP": 409,
    "ERR_BENEFIT_PERIOD_OVERLAP": 409,
    "ERR_ACCOUNT_NOT_DISCONNECTED": 422,
    "ERR_VENDOR_NOT_ENROLLED": 409,
    "ERR_POOL_DEPLETED": 409,
    "ERR_BENEFIT_EXCEEDS_AVAILABLE": 409,
    "ERR_PAYMENT_NOT_REMITTED": 409,
    "ERR_STALE_POOL_VERSION": 412,
}

ROLES = {"Applicant", "Caseworker", "VendorAgent", "ProgramAdmin"}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP.get(error_id, 400)
        self.message = message or error_id


# --------------------------------------------------------------------------
# Response envelope (§1.0 / PRD §2.2)
# --------------------------------------------------------------------------
def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _base_meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": wall_iso()}


def object_response(data, code=200):
    body = {"meta": _base_meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), code


def list_response(items, limit, offset, total_count):
    meta = _base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(error_id, message):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), ERROR_HTTP.get(error_id, 400)


# --------------------------------------------------------------------------
# Identity / RBAC (§2.1, §2.9)
# --------------------------------------------------------------------------
def identity():
    """Return (role, user_id). Raise ERR_UNAUTHENTICATED if role missing/unknown."""
    role = request.headers.get("X-User-Role")
    if not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or unknown X-User-Role")
    user_id = request.headers.get("X-User-ID")
    return role, user_id


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN", "Role not permitted for this operation")


def endpoint(roles):
    """Decorator: authenticate, gate by role, and pass (role, user_id) to handler."""
    def deco(fn):
        @wraps(fn)
        def wrapper(**kwargs):
            role, user_id = identity()
            require_role(role, roles)
            return fn(role, user_id, **kwargs)
        return wrapper
    return deco


# --------------------------------------------------------------------------
# Body / query validation helpers (ERR_VALIDATION unless noted)
# --------------------------------------------------------------------------
def get_body(required=True):
    data = request.get_json(silent=True)
    if data is None:
        if required:
            raise ApiError("ERR_VALIDATION", "Request body must be a JSON object")
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object")
    return data


def _present(body, field):
    return field in body and body[field] is not None


def req_str(body, field):
    if not _present(body, field):
        raise ApiError("ERR_VALIDATION", "Missing required field: %s" % field)
    v = body[field]
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", "Field %s must be a non-empty string" % field)
    return v


def req_int(body, field, minimum=None, maximum=None, gt=None):
    if not _present(body, field):
        raise ApiError("ERR_VALIDATION", "Missing required field: %s" % field)
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", "Field %s must be an integer" % field)
    _check_int_bounds(field, v, minimum, maximum, gt)
    return v


def opt_int(body, field, default, minimum=None, maximum=None, gt=None):
    if not _present(body, field):
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", "Field %s must be an integer" % field)
    _check_int_bounds(field, v, minimum, maximum, gt)
    return v


def _check_int_bounds(field, v, minimum, maximum, gt):
    if minimum is not None and v < minimum:
        raise ApiError("ERR_VALIDATION", "Field %s must be >= %s" % (field, minimum))
    if maximum is not None and v > maximum:
        raise ApiError("ERR_VALIDATION", "Field %s must be <= %s" % (field, maximum))
    if gt is not None and v <= gt:
        raise ApiError("ERR_VALIDATION", "Field %s must be > %s" % (field, gt))


def req_enum(body, field, choices):
    v = req_str(body, field)
    if v not in choices:
        raise ApiError("ERR_VALIDATION", "Field %s must be one of %s" % (field, sorted(choices)))
    return v


def opt_bool(body, field, default=False):
    if not _present(body, field):
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", "Field %s must be a boolean" % field)
    return v


def opt_str(body, field, default=None):
    if not _present(body, field):
        return default
    v = body[field]
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", "Field %s must be a string" % field)
    return v


def req_datetime(body, field):
    from store import parse_dt
    if not _present(body, field):
        raise ApiError("ERR_VALIDATION", "Missing required field: %s" % field)
    try:
        return parse_dt(body[field])
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", "Field %s must be an ISO-8601 datetime" % field)


# --------------------------------------------------------------------------
# Pagination (§2.3)
# --------------------------------------------------------------------------
def parse_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise ApiError("ERR_VALIDATION", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_VALIDATION", "limit out of bounds [1,100]")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise ApiError("ERR_VALIDATION", "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    return page, total
