"""Response envelope helpers per SCAFFOLD section 1.0 / PRD section 2.2."""

import secrets
import string

from flask import jsonify

import clock


def _request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def success(data, response_type="object", status=200, pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": clock.now_iso(),
    }
    if pagination is not None:
        meta["limit"] = pagination["limit"]
        meta["offset"] = pagination["offset"]
        meta["total_count"] = pagination["total_count"]
        meta["has_more"] = pagination["has_more"]
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


def error(error_id, message, http_status):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": clock.now_iso(),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
