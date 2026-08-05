"""Standard response envelope helpers."""
import random
import string
from datetime import datetime, timezone
from flask import jsonify


def _request_id():
    alnum = string.ascii_letters + string.digits
    return "req_" + "".join(random.choice(alnum) for _ in range(20))


def _request_ts():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (dt.microsecond // 1000)


def _base_meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": _request_ts()}


def serialize(entity):
    """Strip internal (underscore-prefixed) keys."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def object_response(data, code=200):
    body = {"meta": _base_meta(), "response_type": "object", "data": data or {}}
    return jsonify(body), code


def array_response(items, limit, offset, total_count):
    meta = _base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + limit) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(error_id, message, http_status):
    meta = _base_meta()
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
