"""Standard response-envelope helpers.

Envelope shape is taken verbatim from PRD §2.2 and SCAFFOLD §1.0:

  success: { "meta": { "api_request_id", "api_request_timestamp", [pagination] },
             "response_type": "object" | "array", "data": {} }
  error:   { "meta": { "api_request_id", "api_request_timestamp" },
             "response_type": "error",
             "data": { "error_id", "message" } }
"""
import datetime
import random
import string

from flask import jsonify


def _request_id():
    # "api_request_id" is a server-generated unique id starting with "req_".
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def _timestamp():
    # ISO 8601 UTC with three fractional digits (milliseconds), 'Z' suffix.
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _timestamp(),
    }
    if extra:
        meta.update(extra)
    return meta


def object_response(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def array_response(data, limit, offset, total_count, status=200):
    has_more = (offset + len(data)) < total_count
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        }),
        "response_type": "array",
        "data": data,
    }
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), status
