"""Standard response envelope helpers (PRD §2.2, SCAFFOLD §1.0).

Success envelope:
  { "meta": { "api_request_id": "req_xxx", "api_request_timestamp": "ISO8601",
              [ "limit", "offset", "total_count", "has_more" for lists ] },
    "response_type": "object" | "array",
    "data": {} | [] }

Error envelope:
  { "meta": { "api_request_id", "api_request_timestamp" },
    "response_type": "error",
    "data": { "error_id": "ERR_XXX", "message": "..." } }
"""
import random
import string

from flask import jsonify

import db


_ALNUM = string.ascii_letters + string.digits


def _request_id():
    # api_request_id starts with "req_" (PRD §2.2).
    return "req_" + "".join(random.choices(_ALNUM, k=20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.now_iso(),
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


def array_response(items, limit, offset, total_count, has_more, status=200):
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        }),
        "response_type": "array",
        "data": items,
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
