"""Response envelope helpers (SCAFFOLD 1.0 / PRD 2.2-2.3)."""
from flask import jsonify

from util import fmt_ts, new_req_id, now
from errors import ApiError


def _meta():
    return {
        "api_request_id": new_req_id(),
        "api_request_timestamp": fmt_ts(now()),
    }


def success_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + limit) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def error_from_spec(spec, message):
    error_id, status = spec
    return error_response(ApiError(error_id, message, status))
