"""Standard response envelope helpers (PRD §2.2).

Success: {"meta": {"api_request_id", "api_request_timestamp", [pagination]},
          "response_type": "object" | "array", "data": ...}
Error:   {"meta": {"api_request_id", "api_request_timestamp"},
          "response_type": "error", "data": {"error_id", "message"}}
"""
import uuid

from flask import jsonify

from db import iso, now


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex,
        "api_request_timestamp": iso(now()),
    }


def success_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def success_list(items, pagination):
    meta = _meta()
    meta["limit"] = pagination["limit"]
    meta["offset"] = pagination["offset"]
    meta["total_count"] = pagination["total_count"]
    meta["has_more"] = pagination["has_more"]
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status
