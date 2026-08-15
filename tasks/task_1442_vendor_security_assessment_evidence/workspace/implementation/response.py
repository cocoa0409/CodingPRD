"""Response envelope helpers (PRD §2.2 / §2.3).

Success: {"meta": {"api_request_id", "api_request_timestamp", [pagination]},
          "response_type": "object" | "array", "data": ...}
Error:   {"meta": {"api_request_id", "api_request_timestamp"},
          "response_type": "error", "data": {"error_id", "message"}}
"""
import secrets
import string

from flask import jsonify

import util


def _meta(pagination=None):
    rid = "req_" + "".join(
        secrets.choice(string.ascii_letters + string.digits) for _ in range(20)
    )
    meta = {
        "api_request_id": rid,
        "api_request_timestamp": util.iso(util.now()),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def ok(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def ok_list(items, limit, offset, total_count):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    body = {"meta": _meta(pagination), "response_type": "array", "data": items}
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
