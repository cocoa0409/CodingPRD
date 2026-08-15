"""Standard response envelope helpers (PRD §2.2 / §2.3)."""
import uuid

from flask import jsonify

from db import fmt_ts, now


def _meta_base():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": fmt_ts(now()),
    }


def ok_object(data, status=200):
    body = {"meta": _meta_base(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    meta = _meta_base()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta_base(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
