"""Response envelope helpers (PRD section 2.2)."""
import secrets

from flask import jsonify

from util import CLOCK


def _meta():
    return {
        "api_request_id": "req_" + secrets.token_hex(12),
        "api_request_timestamp": CLOCK.stamp(),
    }


def ok_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def ok_list(items, total_count, limit, offset, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    resp = jsonify(body)
    resp.status_code = err.http_status
    return resp
