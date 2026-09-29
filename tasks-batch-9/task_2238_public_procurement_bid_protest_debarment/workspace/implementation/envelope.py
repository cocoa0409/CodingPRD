"""Response envelope helpers (PRD §2.2)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _timestamp():
    dt = datetime.now(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def base_meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": _timestamp()}


def object_response(data, status=200):
    body = {"meta": base_meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def list_response(items, limit, offset, total_count):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
