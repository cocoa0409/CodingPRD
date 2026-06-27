"""Standard response-envelope helpers (PRD §2.2, SCAFFOLD §1.0).

success: { meta:{api_request_id, api_request_timestamp [, pagination]},
           response_type: "object"|"array", data: {} | [] }
error:   { meta:{api_request_id, api_request_timestamp},
           response_type: "error", data: { error_id, message } }
"""
from flask import jsonify

from util import iso_now, new_request_id


def _meta(clock):
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": iso_now(clock.get()),
    }


def ok_object(clock, data, status=200):
    body = {"meta": _meta(clock), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_array(clock, items, limit, offset, total_count, status=200):
    meta = _meta(clock)
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def error_response(clock, error_id, message, http_status):
    body = {
        "meta": _meta(clock),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
