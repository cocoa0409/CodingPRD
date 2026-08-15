"""Response envelope per PRD section 2.2."""
import secrets

from flask import jsonify

from clock import now_ts


def _meta():
    return {
        "api_request_id": "req_" + secrets.token_hex(10),
        "api_request_timestamp": now_ts(),
    }


def ok_object(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def err_response(error_id, message, status):
    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }), status
