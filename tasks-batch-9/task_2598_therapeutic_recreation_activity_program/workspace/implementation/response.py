"""Response envelope helpers (PRD 2.2 / 2.3)."""
import random
import string

from flask import jsonify

from db import store

_ALNUM = string.ascii_uppercase + string.digits

PAGINATION_DEFAULTS = {"limit": 10, "limit_min": 1, "limit_max": 100, "offset": 0}


def api_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def base_meta():
    return {
        "api_request_id": api_request_id(),
        "api_request_timestamp": store.now_iso(),
    }


def object_response(data, status=200):
    body = {
        "meta": base_meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def empty_response(status=200):
    return object_response({}, status)


def list_response(rows, limit, offset, total_count, status=200):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
