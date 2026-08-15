"""Standard response envelope helpers (SCAFFOLD §1.0 / PRD §2.2).

Success: {"meta": {api_request_id, api_request_timestamp[, limit, offset,
                    total_count, has_more]}, "response_type": "object"|"array",
          "data": ...}
Error:   {"meta": {api_request_id, api_request_timestamp},
          "response_type": "error", "data": {"error_id", "message"}}
"""

from flask import jsonify

import db


def _meta():
    return {
        "api_request_id": db.new_request_id(),
        "api_request_timestamp": db.now_iso(),
    }


def success(data, code=200):
    body = {
        "meta": _meta(),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    return jsonify(body), code


def success_list(items, total_count, limit, offset, code=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), code


def error(api_err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": api_err.error_id, "message": api_err.message},
    }
    return jsonify(body), api_err.http_status
