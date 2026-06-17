"""Standard response envelope helpers (PRD §2.2, §2.3)."""
from flask import jsonify

from util import new_request_id, iso_now, now_utc


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": iso_now(now_utc()),
    }


def success(data, status=200, response_type="object", pagination=None):
    """Build a success envelope. pagination, when given, merges into meta."""
    meta = _meta()
    if pagination:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def list_success(items, limit, offset, total_count):
    """Build an array response with pagination fields in meta (PRD §2.3)."""
    has_more = (offset + len(items)) < total_count
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    return success(items, status=200, response_type="array", pagination=pagination)


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp
