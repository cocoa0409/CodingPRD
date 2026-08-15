"""Standard response envelope helpers (SCAFFOLD §1.0 / PRD §2.2).

Success:
    { "meta": { "api_request_id": "req_...", "api_request_timestamp": "ISO8601",
                "limit": N, "offset": N, "total_count": N, "has_more": bool },
      "response_type": "object" | "array",
      "data": ... }
Error:
    { "meta": { "api_request_id": "...", "api_request_timestamp": "..." },
      "response_type": "error",
      "data": { "error_id": "...", "message": "..." } }
"""
import random
import string

from flask import jsonify

import clock


def _request_id():
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def _meta(pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": clock.now_iso(),
    }
    if pagination is not None:
        meta["limit"] = pagination["limit"]
        meta["offset"] = pagination["offset"]
        meta["total_count"] = pagination["total_count"]
        meta["has_more"] = pagination["has_more"]
    return meta


def _public(value):
    """Recursively strip internal (underscore-prefixed) fields from resource
    dicts before serialization; envelopes carry only API-visible fields."""
    if isinstance(value, dict):
        return {k: _public(v) for k, v in value.items()
                if not (isinstance(k, str) and k.startswith("_"))}
    if isinstance(value, list):
        return [_public(v) for v in value]
    return value


def success_object(data, http_status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": _public(data),
    }
    return jsonify(body), http_status


def success_list(items, pagination, http_status=200):
    body = {
        "meta": _meta(pagination),
        "response_type": "array",
        "data": _public(items),
    }
    return jsonify(body), http_status


def error(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
