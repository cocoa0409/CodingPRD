"""Response envelope helpers — match PRD §2.2 exactly."""
from flask import jsonify, g

import db
import clock


def _meta_base():
    return {
        "api_request_id": getattr(g, "api_request_id", None) or db.new_request_id(),
        "api_request_timestamp": clock.iso8601_ms(clock.now_utc()),
    }


def success(data, status=200):
    meta = _meta_base()
    body = {
        "meta": meta,
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_list(items, limit, offset, total_count, status=200):
    meta = _meta_base()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + limit) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error(error_id, message, status):
    meta = _meta_base()
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), status
