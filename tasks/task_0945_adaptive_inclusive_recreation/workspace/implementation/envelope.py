"""Response envelope helpers (PRD 2.2)."""

from flask import jsonify

from store import new_request_id, server_now


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": server_now(),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    response = jsonify(body)
    response.status_code = status
    return response


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    response = jsonify(body)
    response.status_code = 200
    return response


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    response = jsonify(body)
    response.status_code = http_status
    return response
