"""Standard response envelope helpers (PRD §2.2).

Success: { "meta": {api_request_id, api_request_timestamp[, pagination]},
           "response_type": "object" | "array", "data": ... }
Error:   { "meta": {api_request_id, api_request_timestamp},
           "response_type": "error", "data": { "error_id", "message" } }
"""
import uuid

from flask import jsonify

from db import store
from utils import fmt_ts


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex,
        "api_request_timestamp": fmt_ts(store.now()),
    }


def success(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.status
