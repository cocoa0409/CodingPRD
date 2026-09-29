"""Response envelope helpers (PRD S2.2 / SCAFFOLD response_envelope).

    {"meta": {...}, "response_type": "object"|"array"|"error", "data": ...}
"""

import random
import string

from flask import jsonify

from store import db

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.now_iso(),
    }


def object_response(data, code=200):
    body = {
        "meta": base_meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), code


def empty_response(code=200):
    return object_response({}, code)


def list_response(rows, limit, offset, total_count):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), 200


def error_response(error_id, message, http_status):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
