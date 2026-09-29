"""Standard response envelope helpers (PRD section 2.2)."""
import secrets
import string

from flask import jsonify

import db
from utils import fmt_ts

_ALPHABET = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(secrets.choice(_ALPHABET) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_ts(db.now()),
    }


def ok_object(data, status=200):
    resp = jsonify({"meta": _meta(), "response_type": "object", "data": data})
    resp.status_code = status
    return resp


def ok_list(items, total_count, limit, offset, has_more, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = has_more
    resp = jsonify({"meta": meta, "response_type": "array", "data": items})
    resp.status_code = status
    return resp


def error_body(error_id, message, http_status):
    resp = jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    })
    resp.status_code = http_status
    return resp
