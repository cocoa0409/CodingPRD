"""Response envelope helpers per PRD section 2.2."""

import random
import string

from flask import jsonify

from db import now
from utils import fmt_dt


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=22))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_dt(now()),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, total_count, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status
