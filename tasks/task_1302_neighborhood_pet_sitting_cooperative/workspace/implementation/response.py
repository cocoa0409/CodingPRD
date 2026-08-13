"""Standard response envelope helpers (PRD §2.2)."""

from flask import jsonify

import clock
from util import fmt_dt, new_req_id


def _meta():
    return {
        "api_request_id": new_req_id(),
        "api_request_timestamp": fmt_dt(clock.now()),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(items, total_count, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def ok_array(items):
    """Array responses without pagination (0-or-1 element lookups)."""
    return jsonify({"meta": _meta(), "response_type": "array", "data": items}), 200


def error_resp(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.status
