"""Uniform response envelope."""
import random
import string

from flask import jsonify

import clock

_ALPHABET = string.ascii_lowercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALPHABET) for _ in range(16))


def base_meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": clock.now_iso(),
    }


def obj(data, status=200):
    body = {
        "meta": base_meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def collection(rows, limit, offset, total_count, status=200):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), status


def error(error_id, message, status):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
