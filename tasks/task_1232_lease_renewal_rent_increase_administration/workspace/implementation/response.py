"""Response envelope helpers — matches SCAFFOLD response_envelope exactly."""

from flask import jsonify

from db import new_request_id, utc_now_iso


def success_object(data, status_code=200):
    body = {
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": utc_now_iso(),
        },
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status_code


def success_list(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": utc_now_iso(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(error_id, http_status, message):
    body = {
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": utc_now_iso(),
        },
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message or error_id,
        },
    }
    return jsonify(body), http_status
