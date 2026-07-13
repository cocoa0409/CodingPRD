"""Standard response-envelope helpers (PRD 2.2)."""
import random
import string

from flask import jsonify

from store import now, fmt_dt


def _request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def _base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_dt(now()),
    }


def object_response(data, status=200):
    body = {
        "meta": _base_meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def array_response(items, limit, offset, total_count, status=200):
    meta = _base_meta()
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


def error_response(error_id, message, status):
    meta = _base_meta()
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
