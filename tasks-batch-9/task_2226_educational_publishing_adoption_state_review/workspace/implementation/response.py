"""Standard response envelope helpers (PRD 2.2)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

_ALNUM = string.ascii_uppercase + string.digits


def _request_meta():
    stamp = datetime.now(timezone.utc)
    return {
        "api_request_id": "req_" + "".join(random.choice(_ALNUM) for _ in range(20)),
        "api_request_timestamp": stamp.strftime("%Y-%m-%dT%H:%M:%S.")
        + "%03dZ" % (stamp.microsecond // 1000),
    }


def respond(data, status=200):
    body = {
        "meta": _request_meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def respond_list(items, total_count, limit, offset):
    meta = _request_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def respond_error(error_id, message, status):
    body = {
        "meta": _request_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
