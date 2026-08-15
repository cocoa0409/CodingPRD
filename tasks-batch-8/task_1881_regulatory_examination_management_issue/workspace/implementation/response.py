"""Standard response envelope helpers (scaffold response_envelope / PRD §2.2)."""
import secrets
from datetime import datetime, timezone

from flask import jsonify

from util import fmt_dt


def _meta():
    return {
        "api_request_id": "req_" + secrets.token_hex(12),
        "api_request_timestamp": fmt_dt(datetime.now(timezone.utc)),
    }


def ok_obj(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def ok_list(items, limit, offset, total_count):
    m = _meta()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total_count
    m["has_more"] = (offset + len(items)) < total_count
    body = {"meta": m, "response_type": "array", "data": items}
    return jsonify(body), 200


def err(error_id, status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
