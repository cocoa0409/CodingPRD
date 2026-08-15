"""Response envelope helpers (PRD section 2.2).

Success: {"meta": {api_request_id, api_request_timestamp[, pagination]},
          "response_type": "object" | "array", "data": ...}
Error:   {"meta": {...}, "response_type": "error",
          "data": {"error_id": ..., "message": ...}}
"""

import secrets
import string

from flask import jsonify

from db import store
from timeutil import fmt_dt

_ALPHABET = string.ascii_letters + string.digits


def _request_id():
    return "req_" + "".join(secrets.choice(_ALPHABET) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_dt(store.clock),
    }


def ok_object(data, status=200):
    resp = jsonify({"meta": _meta(), "response_type": "object", "data": data})
    resp.status_code = status
    return resp


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": items})


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    resp = jsonify(body)
    resp.status_code = err.http_status
    return resp
