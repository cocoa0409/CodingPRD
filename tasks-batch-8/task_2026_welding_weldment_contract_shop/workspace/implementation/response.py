"""Standard response envelope helpers (scaffold §1.0 / PRD §2.2)."""

import random
import string
from flask import jsonify

from helpers import wall_timestamp


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta_base():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": wall_timestamp(),
    }


def success_object(data, status=200):
    body = {
        "meta": _meta_base(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_list(items, limit, offset, total_count, status=200):
    meta = _meta_base()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta_base(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
