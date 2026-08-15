"""Standard response envelope helpers (SCAFFOLD section 1.0 / PRD 2.2)."""
import secrets
import string

from flask import jsonify

from util import now_wall_iso


def _request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(22))


def success(data, status=200, response_type="object", pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_wall_iso(),
    }
    if pagination is not None:
        meta["limit"] = pagination["limit"]
        meta["offset"] = pagination["offset"]
        meta["total_count"] = pagination["total_count"]
        meta["has_more"] = pagination["has_more"]
    body = {"meta": meta, "response_type": response_type, "data": data}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error(error_id, message, status):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": now_wall_iso(),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp
