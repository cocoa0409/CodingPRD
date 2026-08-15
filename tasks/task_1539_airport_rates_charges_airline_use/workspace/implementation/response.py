"""Response envelope helpers — exact structure from scaffold response_envelope.

Success: {"meta": {api_request_id, api_request_timestamp[, limit, offset,
          total_count, has_more]}, "response_type": "object"|"array", "data": ...}
Error:   {"meta": {api_request_id, api_request_timestamp},
          "response_type": "error", "data": {"error_id", "message"}}
"""
from flask import jsonify

from util import new_request_id, wall_now_iso


def _meta(pagination=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": wall_now_iso(),
    }
    if pagination is not None:
        meta["limit"] = pagination["limit"]
        meta["offset"] = pagination["offset"]
        meta["total_count"] = pagination["total_count"]
        meta["has_more"] = pagination["has_more"]
    return meta


def success_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def success_list(items, pagination, status=200):
    body = {"meta": _meta(pagination), "response_type": "array", "data": items}
    return jsonify(body), status


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status
