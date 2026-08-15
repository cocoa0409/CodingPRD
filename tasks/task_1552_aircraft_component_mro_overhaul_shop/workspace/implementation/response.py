"""Response envelope helpers — exact structure from SCAFFOLD.response_envelope."""
import random
import string

from flask import jsonify

from db import now_iso


def _meta():
    return {
        "api_request_id": "req_" + "".join(
            random.choice(string.ascii_letters + string.digits) for _ in range(20)
        ),
        "api_request_timestamp": now_iso(),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + limit) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(error_id, status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
