"""Standard response envelope helpers (PRD §2.2).

Success envelope:
  { "meta": { "api_request_id": "req_...", "api_request_timestamp": "ISO" [, pagination] },
    "response_type": "object" | "array", "data": {...} }

Error envelope:
  { "meta": {...}, "response_type": "error",
    "data": { "error_id": "ERR_XXX", "message": "..." } }
"""
import random
import string

from flask import jsonify

from clock import now_iso_millis


def _request_id():
    alphabet = string.ascii_uppercase + string.ascii_lowercase + string.digits
    return "req_" + "".join(random.choices(alphabet, k=20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso_millis(),
    }
    if extra:
        meta.update(extra)
    return meta


def success(data, http_status=200, response_type="object", pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp


def error_response(error_id, message):
    from errors import ERROR_CATALOG

    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = ERROR_CATALOG.get(error_id, 400)
    return resp
