"""Response envelope — PRD §2.2."""

import random
import string

from flask import jsonify

from store import fmt_wall, wall_now

_ALNUM = string.ascii_uppercase + string.digits


def _meta():
    token = "".join(random.choice(_ALNUM) for _ in range(20))
    return {
        "api_request_id": "req_" + token,
        "api_request_timestamp": fmt_wall(wall_now()),
    }


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def created(data):
    return object_response(data, 201)


def array_response(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
