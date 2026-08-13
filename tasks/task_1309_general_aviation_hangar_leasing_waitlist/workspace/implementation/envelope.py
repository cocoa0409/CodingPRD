"""Response envelope helpers matching the scaffold's response_envelope spec:
success -> {"meta": {...}, "response_type": "object"|"array", "data": ...}
error   -> {"meta": {...}, "response_type": "error", "data": {"error_id", "message"}}
List responses add limit/offset/total_count/has_more to meta."""
import uuid
from datetime import datetime, timezone

from flask import jsonify

from timeutil import iso_z


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex,
        "api_request_timestamp": iso_z(datetime.now(timezone.utc)),
    }


def success_obj(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def success_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_resp(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
