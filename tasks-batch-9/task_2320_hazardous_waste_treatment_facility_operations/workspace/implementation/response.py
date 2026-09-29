"""Response envelope helpers (SCAFFOLD 1.0 / PRD 2.2)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

_ALPHABET = string.ascii_lowercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALPHABET) for _ in range(20))


def _meta():
    now = datetime.now(timezone.utc)
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": now.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (now.microsecond // 1000),
    }


def ok(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def created(data):
    return ok(data, 201)


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = offset + len(items) < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error_response(error_id, message, status):
    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }), status
