"""Standard response envelope per SCAFFOLD response_envelope / PRD section 2.2."""
from flask import jsonify

import clock
from util import fmt_ts, new_request_id


def _meta(pagination=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": fmt_ts(clock.now()),
    }
    if pagination is not None:
        limit, offset, total = pagination
        meta["limit"] = limit
        meta["offset"] = offset
        meta["total_count"] = total
        meta["has_more"] = (offset + limit) < total
    return meta


def ok(data, status=200, pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    return jsonify(body), status


def error_response(error_id: str, http_status: int, message: str):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
