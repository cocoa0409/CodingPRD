"""Standard response envelope helpers (PRD section 2.2)."""

import uuid
from flask import jsonify

from db import CLOCK


def _request_id():
    return "req_" + uuid.uuid4().hex[:20]


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": CLOCK.now_iso(),
    }


def success_object(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
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


def error_response(api_error):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": api_error.error_id,
            "message": api_error.message,
        },
    }
    return jsonify(body), api_error.http_status
