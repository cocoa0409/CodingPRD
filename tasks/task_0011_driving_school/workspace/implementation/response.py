from flask import jsonify

from clock import CLOCK
from db import new_request_id


def _meta_base():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": CLOCK.iso(),
    }


def success_object(data, status=200):
    body = {
        "meta": _meta_base(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_array(data, limit, offset, total_count, status=200):
    meta = _meta_base()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = offset + limit < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": data,
    }
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta_base(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message or error_id,
        },
    }
    return jsonify(body), status
