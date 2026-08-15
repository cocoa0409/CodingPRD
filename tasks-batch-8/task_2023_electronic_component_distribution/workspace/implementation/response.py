"""Response envelope helpers matching scaffold response_envelope exactly."""

import random
import string

from flask import jsonify

import clock


def _request_id() -> str:
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def _meta() -> dict:
    # The server's clock is the logical clock (PRD 2.4) — never wall-clock time.
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": clock.now().strftime("%Y-%m-%dT%H:%M:%S.%f")[:23] + "Z",
    }


def success(data, status: int = 200, response_type: str = "object", pagination=None):
    meta = _meta()
    if pagination is not None:
        meta["limit"] = pagination["limit"]
        meta["offset"] = pagination["offset"]
        meta["total_count"] = pagination["total_count"]
        meta["has_more"] = pagination["has_more"]
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


def error(error_id: str, message: str, http_status: int):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
