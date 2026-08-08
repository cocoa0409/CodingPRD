"""Standard response envelope helpers (PRD section 2.2)."""

import random
import string

from flask import jsonify

from clock import LOGICAL_CLOCK, render_datetime

_ALPHANUM = string.ascii_uppercase + string.ascii_lowercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": render_datetime(LOGICAL_CLOCK.now()),
    }


def object_response(data, status=200):
    body = {
        "meta": _base_meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def list_response(rows, limit, offset, total_count, status=200):
    meta = _base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
