"""Standard response envelope helpers (PRD §2.2).

Success envelope:
    { "meta": { "api_request_id": "req_...", "api_request_timestamp": "ISO",
                [pagination fields on lists] },
      "response_type": "object" | "array",
      "data": {} | [] }

Error envelope:
    { "meta": { "api_request_id", "api_request_timestamp" },
      "response_type": "error",
      "data": { "error_id", "message" } }
"""

import random
import string

from flask import jsonify

from clock import now, format_iso8601

_ALPHANUM = string.ascii_letters + string.digits


def _request_id():
    # PRD §2.2: server-generated unique id that starts with "req_".
    return "req_" + "".join(random.choices(_ALPHANUM, k=20))


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": format_iso8601(now()),
    }
    if extra:
        m.update(extra)
    return m


def object_response(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
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
        "data": items,
    }
    return jsonify(body), status


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status
