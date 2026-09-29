"""Response envelope helpers (PRD 2.2, 2.3)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

_ALNUM = string.ascii_uppercase + string.digits


def _meta():
    stamp = datetime.now(timezone.utc)
    return {
        "api_request_id": "req_" + "".join(random.choice(_ALNUM) for _ in range(20)),
        "api_request_timestamp": stamp.strftime("%Y-%m-%dT%H:%M:%S.")
        + "%03dZ" % (stamp.microsecond // 1000),
    }


def ok(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def created(data):
    return ok(data, 201)


def ok_list(rows, limit, offset, total):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(rows)) < total
    return jsonify({"meta": meta, "response_type": "array", "data": rows}), 200


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
