"""Standard response envelope helpers (PRD section 2.2)."""

import random
import string

from flask import jsonify

from db import store
from util import iso_z


def new_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": iso_z(store.now()),
    }


def ok(data, status=200):
    body = {"meta": meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, total_count, limit, offset):
    m = meta()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total_count
    m["has_more"] = (offset + len(items)) < total_count
    return jsonify({"meta": m, "response_type": "array", "data": items}), 200


def error_response(error_id, message, http_status):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
