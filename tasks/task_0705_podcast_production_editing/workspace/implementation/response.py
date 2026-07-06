"""Standard response envelope (PRD §2.2, scaffold §1.0 — emit verbatim).

success: { "meta": { "api_request_id", "api_request_timestamp", <pagination?> },
           "response_type": "object" | "array", "data": {} }
error:   { "meta": { "api_request_id", "api_request_timestamp" },
           "response_type": "error",
           "data": { "error_id", "message" } }
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    alnum = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(alnum, k=20))


def _meta():
    # api_request_timestamp is server wall-clock per the envelope example
    # (ISO 8601 UTC, three fractional digits). This is metadata about the HTTP
    # request, distinct from the logical clock used for domain timestamps.
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
    return {"api_request_id": _request_id(), "api_request_timestamp": ts}


def success(data, status=200, response_type="object", pagination=None):
    meta = _meta()
    if pagination is not None:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


def object_response(data, status=200):
    return success(data, status=status, response_type="object")


def array_response(items, pagination):
    return success(items, status=200, response_type="array", pagination=pagination)


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
