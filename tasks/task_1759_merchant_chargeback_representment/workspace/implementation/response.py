"""Standard response envelope helpers (SCAFFOLD response_envelope / PRD 2.2)."""

import uuid
from datetime import datetime, timezone

from flask import jsonify

from util import iso3


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": iso3(datetime.now(timezone.utc)),
    }


def ok_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
