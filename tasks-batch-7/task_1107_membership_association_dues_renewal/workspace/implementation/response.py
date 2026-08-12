"""Standard response envelope helpers — envelope per SCAFFOLD response_envelope / PRD §2.2."""
from flask import jsonify
import db


def success(data, status=200, response_type="object", pagination=None):
    meta = {
        "api_request_id": db.req_id(),
        "api_request_timestamp": db.iso(db.now_utc()),
    }
    if pagination is not None:
        meta["limit"] = pagination["limit"]
        meta["offset"] = pagination["offset"]
        meta["total_count"] = pagination["total_count"]
        meta["has_more"] = pagination["has_more"]
    body = {
        "meta": meta,
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def error(err):
    body = {
        "meta": {
            "api_request_id": db.req_id(),
            "api_request_timestamp": db.iso(db.now_utc()),
        },
        "response_type": "error",
        "data": {
            "error_id": err.error_id,
            "message": err.message,
        },
    }
    return jsonify(body), err.http_status
