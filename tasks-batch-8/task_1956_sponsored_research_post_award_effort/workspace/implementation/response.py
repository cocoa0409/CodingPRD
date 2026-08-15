"""Response envelope helpers (PRD 2.2 / 2.3).

Success: {"meta": {api_request_id, api_request_timestamp[, limit, offset,
total_count, has_more]}, "response_type": "object"|"array", "data": ...}
Error:   {"meta": {...}, "response_type": "error",
          "data": {"error_id": ..., "message": ...}}
"""
import random
import string

from flask import jsonify

from util import now_iso


def _rid():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(extra=None):
    m = {"api_request_id": _rid(), "api_request_timestamp": now_iso()}
    if extra:
        m.update(extra)
    return m


def ok(data, code=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), code


def ok_created(data):
    return ok(data, code=201)


def ok_list(items, total_count, limit, offset):
    extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + len(items) < total_count,
    }
    return jsonify({"meta": _meta(extra), "response_type": "array", "data": items}), 200


def error_resp(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.status
