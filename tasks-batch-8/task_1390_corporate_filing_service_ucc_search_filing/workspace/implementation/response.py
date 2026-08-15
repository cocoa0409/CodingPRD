"""Standard response envelope helpers (PRD section 2.2).

Success: {"meta": {api_request_id, api_request_timestamp[, limit, offset,
                   total_count, has_more]}, "response_type": "object"|"array",
          "data": ...}
Error:   {"meta": {api_request_id, api_request_timestamp},
          "response_type": "error", "data": {"error_id", "message"}}
"""
import secrets
import string

from flask import jsonify

import db
from util import fmt_dt_ms

_ALPHANUM = string.ascii_letters + string.digits


def _meta():
    return {
        "api_request_id": "req_" + "".join(secrets.choice(_ALPHANUM) for _ in range(20)),
        "api_request_timestamp": fmt_dt_ms(db.now()),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, total_count, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status
