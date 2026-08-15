"""Standard response envelope helpers per SCAFFOLD response_envelope."""

import random
import string
from flask import jsonify
from db import iso_z
from datetime import datetime, timezone


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta():
    # wall-clock for the meta timestamp is fine (request metadata, not business time)
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso_z(datetime.now(timezone.utc)),
    }


def success_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
