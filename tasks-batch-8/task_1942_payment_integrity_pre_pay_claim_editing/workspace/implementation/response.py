"""Standard response envelope per PRD Section 2.2."""

import random
import string

from flask import jsonify

import db


def _request_id() -> str:
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def _meta() -> dict:
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.fmt_ts(db.now()),
    }


def success_object(data: dict, status: int = 200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def success_list(items: list, limit: int, offset: int, total_count: int, status: int = 200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def error_response(error_id: str, http_status: int, message: str):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
