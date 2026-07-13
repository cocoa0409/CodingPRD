"""Response envelope helpers and the API error type / catalogue."""
import random
import string

from flask import jsonify

from util import format_iso, now_utc

# Error id -> HTTP status (from the PRD/scaffold error catalogue).
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_VALIDATION": 422,
    "ERR_PROPERTY_NOT_FOUND": 404,
    "ERR_REGISTRANT_NOT_FOUND": 404,
    "ERR_INSPECTION_NOT_FOUND": 404,
    "ERR_VIOLATION_NOT_FOUND": 404,
    "ERR_FINE_NOT_FOUND": 404,
    "ERR_LIEN_NOT_FOUND": 404,
    "ERR_ABATEMENT_ORDER_NOT_FOUND": 404,
    "ERR_RECEIVERSHIP_NOT_FOUND": 404,
    "ERR_DEMOLITION_NOT_FOUND": 404,
    "ERR_LICENSE_REQUIRED": 422,
    "ERR_TYPE_MISMATCH": 422,
    "ERR_DUPLICATE_PARCEL": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_INVALID_WINDOW": 422,
    "ERR_INSPECTOR_DOUBLE_BOOKED": 409,
    "ERR_ABATEMENT_WINDOW_CONFLICT": 409,
    "ERR_CURE_PERIOD_ACTIVE": 409,
    "ERR_FORECLOSURE_STAGE_INVALID": 409,
    "ERR_NO_ABATABLE_VIOLATION": 409,
    "ERR_INSUFFICIENT_VIOLATIONS": 409,
    "ERR_BALANCE_BELOW_DEMOLITION_THRESHOLD": 409,
    "ERR_LIEN_AMOUNT_TOO_LOW": 409,
    "ERR_PROPERTY_NOT_REO": 409,
    "ERR_FORECLOSURE_TERMINAL": 409,
    "ERR_STALE_PROPERTY_VERSION": 412,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP.get(error_id, 400)
        self.message = message or error_id


def _request_id():
    alnum = string.ascii_letters + string.digits
    return "req_" + "".join(random.choice(alnum) for _ in range(20))


def _base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": format_iso(now_utc()),
    }


def success(data, status=200, response_type="object", pagination=None):
    meta = _base_meta()
    if pagination:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def list_response(items, total_count, limit, offset, status=200):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + len(items) < total_count,
    }
    return success(items, status=status, response_type="array", pagination=pagination)


def error_response(err):
    meta = _base_meta()
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    resp = jsonify(body)
    resp.status_code = err.http_status
    return resp
