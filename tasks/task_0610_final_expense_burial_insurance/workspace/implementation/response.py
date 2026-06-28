"""Standard response envelope helpers (PRD §2.2)."""
import random
import string

from flask import jsonify

from clock import now_iso_millis


def _request_id():
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso_millis(),
    }
    if extra:
        meta.update(extra)
    return meta


def success(data, status=200, response_type="object", pagination=None):
    """Build a standard success envelope.

    response_type is "object" for a single resource, "array" for a list.
    pagination, when present, contributes limit/offset/total_count/has_more
    into the meta object (list endpoints only).
    """
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
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
