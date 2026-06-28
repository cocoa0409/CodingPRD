"""Standard response envelope helpers (PRD §2.2).

Success:
  { "meta": { "api_request_id": "req_...", "api_request_timestamp": "ISO",
              [list-only: "limit","offset","total_count","has_more"] },
    "response_type": "object" | "array",
    "data": {} | [] }

Error:
  { "meta": { "api_request_id", "api_request_timestamp" },
    "response_type": "error",
    "data": { "error_id", "message" } }
"""

import random
import string

from flask import jsonify

from db import system_now_iso

# Fields internal to the store that must never be serialized to clients.
_PRIVATE_FIELDS = ("_seq",)


def _request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(alphabet, k=20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": system_now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def _clean(record):
    if isinstance(record, dict):
        return {k: v for k, v in record.items() if k not in _PRIVATE_FIELDS}
    return record


def object_response(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": _clean(data) if data is not None else {},
    }
    return jsonify(body), status


def array_response(items, limit, offset, total_count, status=200):
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        }),
        "response_type": "array",
        "data": [_clean(it) for it in items],
    }
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
