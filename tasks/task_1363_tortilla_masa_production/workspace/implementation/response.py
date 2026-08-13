"""Standard response envelope per PRD section 2.2 / 2.3."""
import secrets
from flask import jsonify
from db import wall_ts


def _rid():
    return "req_" + secrets.token_hex(8)


def _meta():
    return {"api_request_id": _rid(), "api_request_timestamp": wall_ts()}


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


def error_body(error_id, message):
    return {"meta": _meta(), "response_type": "error",
            "data": {"error_id": error_id, "message": message}}


def err_response(api_error):
    return jsonify(error_body(api_error.error_id, api_error.message)), api_error.http_status
