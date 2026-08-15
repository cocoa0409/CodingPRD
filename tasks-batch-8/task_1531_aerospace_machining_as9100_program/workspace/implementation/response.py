"""Standard response envelope helpers (PRD §2.2 / §2.3)."""

import uuid

from flask import jsonify

from db import db


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": db.now_iso(),
    }


def success_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def success_list(items, pagination, status=200):
    meta = _meta()
    meta["limit"] = pagination["limit"]
    meta["offset"] = pagination["offset"]
    meta["total_count"] = pagination["total_count"]
    meta["has_more"] = pagination["has_more"]
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
