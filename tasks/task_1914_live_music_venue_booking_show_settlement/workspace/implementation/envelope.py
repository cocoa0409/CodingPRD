"""Response envelope helpers (PRD section 2.2 / 2.3).

Success: {"meta": {...}, "response_type": "object"|"array", "data": ...}
Error:   {"meta": {...}, "response_type": "error", "data": {"error_id", "message"}}
List responses add limit/offset/total_count/has_more inside meta.
"""

import secrets

from flask import jsonify

import store


def _meta():
    return {
        "api_request_id": "req_" + secrets.token_hex(12),
        "api_request_timestamp": store.fmt_dt(store.now()),
    }


def ok(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def created(data):
    return ok(data, 201)


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status
