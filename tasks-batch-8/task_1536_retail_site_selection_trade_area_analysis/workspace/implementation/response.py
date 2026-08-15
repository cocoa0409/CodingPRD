"""Standard response envelope helpers (scaffold §1.0 / PRD §2.2)."""

import uuid
from flask import jsonify

from db import db


def _meta_base():
    ts = db.clock
    stamp = ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": stamp,
    }


def ok_object(data, status=200):
    body = {"meta": _meta_base(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    meta = _meta_base()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta_base(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
