"""Response envelope helpers (PRD 2.2)."""

import random
import string

from flask import jsonify

from db import iso, utcnow

_ALNUM = string.ascii_uppercase + string.digits


def make_meta():
    return {
        "api_request_id": "req_" + "".join(random.choice(_ALNUM) for _ in range(20)),
        "api_request_timestamp": iso(utcnow()),
    }


def ok(data, status=200):
    body = {"meta": make_meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def ok_list(items, limit, offset, total):
    meta = make_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = offset + len(items) < total
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def fail(error_id, message, status):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
