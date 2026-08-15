"""Standard response envelope helpers (PRD §2.2 / scaffold §1.0)."""
from flask import jsonify

from util import new_request_id, wall_now_iso


def _meta():
    return {"api_request_id": new_request_id(), "api_request_timestamp": wall_now_iso()}


def ok_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def ok_list(items, total_count, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def no_content():
    return "", 204


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
