"""Standard response envelope helpers (SCAFFOLD 1.0 / PRD §2.2)."""
import random
import string

from flask import jsonify

from db import now_iso


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def ok(data, status=200):
    """Single-resource success envelope."""
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": now_iso(),
        },
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def ok_list(items, pagination):
    """List success envelope with pagination fields in meta (PRD §2.3)."""
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),
    }
    meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(error_id, status, message):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": now_iso(),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
