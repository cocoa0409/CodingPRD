"""Standard response envelope helpers per SCAFFOLD §1.0 / PRD §2.2."""

import random
import string
from flask import jsonify

import db as dbmod


def _request_id():
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return f"req_{suffix}"


def _meta_base():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": dbmod.now_iso(),
    }


def success_object(payload, http_status=200):
    body = {
        "meta": _meta_base(),
        "response_type": "object",
        "data": payload,
    }
    return jsonify(body), http_status


def success_list(items, total_count, limit, offset, http_status=200):
    meta = _meta_base()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + limit) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), http_status


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta_base(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status
