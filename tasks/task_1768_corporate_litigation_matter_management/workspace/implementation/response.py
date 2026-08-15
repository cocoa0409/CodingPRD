"""Standard response envelope helpers (PRD section 2.2)."""
from flask import jsonify

from db import fmt_ts, new_request_id, wall_now


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": fmt_ts(wall_now()),
    }


def ok_object(data, code=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), code


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def err_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status
