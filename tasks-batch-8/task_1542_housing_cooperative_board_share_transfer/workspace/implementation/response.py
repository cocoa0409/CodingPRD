"""Standard response envelope per PRD §2.2."""
import random
import string

from flask import jsonify

from util import wall_now, fmt_iso


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=24))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_iso(wall_now()),
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


def error_resp(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
