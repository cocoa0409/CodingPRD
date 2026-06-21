"""Response envelope helpers (PRD §2.2, SCAFFOLD response_envelope).

Success envelope:
  { "meta": { "api_request_id": "req_...", "api_request_timestamp": ISO8601,
              [pagination fields for lists] },
    "response_type": "object" | "array",
    "data": {} | [] }

Error envelope:
  { "meta": { "api_request_id": ..., "api_request_timestamp": ... },
    "response_type": "error",
    "data": { "error_id": "ERR_XXX", "message": "..." } }
"""

import random
import string

from flask import jsonify

from timeutil import now_iso


_ALPHANUM = string.ascii_letters + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),  # response stamp uses wall clock
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


def array_response(items, limit, offset, total_count, status=200):
    has_more = (offset + len(items)) < total_count
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    body = {
        "meta": _meta(meta_extra),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def empty_response(status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": {},
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
