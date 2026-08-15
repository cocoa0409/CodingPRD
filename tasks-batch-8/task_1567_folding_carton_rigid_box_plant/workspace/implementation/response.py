"""Response envelope helpers (SCAFFOLD §1.0 / PRD §2.2, §2.3)."""

from flask import jsonify

from util import new_request_id, now_iso


def _meta_base():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": now_iso(),
    }


def ok_object(data, status=200):
    body = {
        "meta": _meta_base(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def ok_list(page_items, limit, offset, total_count):
    meta = _meta_base()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(page_items)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": page_items,
    }
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta_base(),
        "response_type": "error",
        "data": {
            "error_id": err.error_id,
            "message": err.message,
        },
    }
    return jsonify(body), err.http_status
