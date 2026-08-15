"""Standard response envelope (PRD 2.2)."""

import secrets
from datetime import datetime, timezone

from flask import jsonify


def _request_meta():
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
    return {
        "api_request_id": "req_" + secrets.token_hex(12),
        "api_request_timestamp": ts,
    }


def ok_object(data, code=200):
    body = {"meta": _request_meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def ok_list(items, limit, offset, total_count, code=200):
    meta = _request_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), code


def error_body(api_error):
    body = {
        "meta": _request_meta(),
        "response_type": "error",
        "data": {"error_id": api_error.error_id, "message": api_error.message},
    }
    return jsonify(body), api_error.http_status
