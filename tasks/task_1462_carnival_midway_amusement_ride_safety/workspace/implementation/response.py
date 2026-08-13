"""Response envelope helpers — exactly the structure fixed by the PRD/SCAFFOLD:

success: {"meta": {"api_request_id", "api_request_timestamp"[, pagination]},
          "response_type": "object" | "array", "data": ...}
error:   {"meta": {"api_request_id", "api_request_timestamp"},
          "response_type": "error", "data": {"error_id", "message"}}
"""
from flask import jsonify

import db


def _meta():
    return {
        "api_request_id": db.new_request_id(),
        "api_request_timestamp": db.now_iso(),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
