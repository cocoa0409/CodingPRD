"""Standard response envelope helpers (PRD §2.2, §2.3)."""

import uuid
from flask import jsonify

import db


def _request_id():
    return "req_" + uuid.uuid4().hex[:20]


def ok(data, status=200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": db.now_iso(),
        },
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def list_ok(items, total_count, limit, offset):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": db.now_iso(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error(error_id, message, http_status):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": db.now_iso(),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
