"""Response envelope helpers (PRD section 2.2 / 2.3)."""
import secrets

from flask import jsonify

from util import wall_now, fmt_ts


def _meta():
    return {
        "api_request_id": "req_" + secrets.token_hex(12),
        "api_request_timestamp": fmt_ts(wall_now_ts()),
    }


def wall_now_ts():
    # request timestamp: wall clock; do not disturb the entity monotonic clock
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


def success_object(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def success_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(error_id, status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
