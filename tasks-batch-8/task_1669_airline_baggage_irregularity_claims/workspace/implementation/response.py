"""Response envelope builders per PRD §2.2."""

from flask import jsonify

from util import new_request_id, now_iso


def success_object(data, http_status=200):
    body = {
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": now_iso(),
        },
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), http_status


def success_list(items, limit, offset, total_count, http_status=200):
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": now_iso(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), http_status


def error_response(error_id: str, message: str, http_status: int):
    body = {
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": now_iso(),
        },
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status
