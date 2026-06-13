"""Standard response envelope helpers (PRD §2.2, scaffold §1.0).

Success object:
  { "meta": { "api_request_id": "req_...", "api_request_timestamp": ISO8601 },
    "response_type": "object" | "array", "data": {...} }
List adds limit/offset/total_count/has_more into meta.
Error:
  { "meta": {...}, "response_type": "error",
    "data": { "error_id": "ERR_XXX", "message": "..." } }
"""

import random
import string

from flask import jsonify

import db

_ALPHANUM = string.ascii_letters + string.digits


def _request_id():
    # api_request_id is a server-generated unique identifier starting with req_.
    return "req_" + "".join(random.choices(_ALPHANUM, k=20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def _strip(record):
    """Remove internal-only fields before serializing a stored record."""
    if isinstance(record, dict):
        return {k: v for k, v in record.items() if not k.startswith("_")}
    return record


def object_response(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": _strip(data) if isinstance(data, dict) else (data or {}),
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
        "data": [_strip(i) for i in items],
    }
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
