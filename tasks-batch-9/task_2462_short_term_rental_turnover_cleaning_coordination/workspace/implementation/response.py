"""Response envelope helpers (PRD 2.2, 2.3)."""

import random
import string

from flask import jsonify

from db import iso, now

_ALPHANUM = string.ascii_uppercase + string.digits


def request_meta():
    return {
        "api_request_id": "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20)),
        "api_request_timestamp": iso(now()),
    }


def ok(data, status=200):
    body = {"meta": request_meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(items, limit, offset, total_count):
    meta = request_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": request_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
