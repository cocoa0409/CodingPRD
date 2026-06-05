"""Response envelope helpers.

PRD section 2.2 (verbatim) / SCAFFOLD section 1.0:

Success:
  { "meta": { "api_request_id": "req_...", "api_request_timestamp": "ISO8601",
              [pagination fields for list endpoints] },
    "response_type": "object" | "array",
    "data": {} }

Error:
  { "meta": { "api_request_id": "...", "api_request_timestamp": "..." },
    "response_type": "error",
    "data": { "error_id": "...", "message": "..." } }
"""

import random
import string

from flask import jsonify

from db import now_iso


def _request_id():
    # PRD 2.2: api_request_id is a server-generated unique identifier that
    # starts with "req_".
    alphanum = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(alphanum, k=20))


def _meta(pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),
    }
    if pagination:
        meta.update(pagination)
    return meta


def object_response(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def array_response(items, limit, offset, total_count):
    # PRD 2.3: pagination bookkeeping lives in the meta object.
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    body = {
        "meta": _meta(pagination),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
