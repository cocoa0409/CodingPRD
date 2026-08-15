"""Response envelope helpers (PRD 2.2).

Success: {"meta": {api_request_id, api_request_timestamp[, limit, offset,
                    total_count, has_more]},
          "response_type": "object" | "array", "data": ...}
Error:   {"meta": {api_request_id, api_request_timestamp},
          "response_type": "error", "data": {"error_id", "message"}}
"""
import secrets
from datetime import datetime, timezone

from flask import jsonify

from timeutil import fmt_dt


def _meta():
    return {
        "api_request_id": "req_" + secrets.token_hex(8),
        "api_request_timestamp": fmt_dt(datetime.now(timezone.utc)),
    }


def success(data, response_type="object", status=200, pagination=None):
    meta = _meta()
    if pagination is not None:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp
