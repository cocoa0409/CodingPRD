"""Response envelope helpers — field names per scaffold response_envelope."""

import uuid

from flask import jsonify

import store


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex,
        "api_request_timestamp": store.now_ts(),
    }


def ok_object(data, code=200):
    payload = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(payload), code


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    payload = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(payload), 200


def error_body(error_id, message, http_status):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(payload), http_status
