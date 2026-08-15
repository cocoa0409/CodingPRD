"""Response envelope helpers (PRD §2.2, SCAFFOLD §1.0).

Success:
  { "meta": { "api_request_id": "req_...", "api_request_timestamp": "...",
              ["limit","offset","total_count","has_more" for lists] },
    "response_type": "object" | "array",
    "data": ... }

Error:
  { "meta": { "api_request_id": ..., "api_request_timestamp": ... },
    "response_type": "error",
    "data": { "error_id": "...", "message": "..." } }
"""

import secrets
import string

from flask import jsonify

import clock

_ALPHANUM = string.ascii_letters + string.digits

# Pagination defaults (SCAFFOLD §1.0 response_envelope.pagination_defaults)
PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100
PAGE_DEFAULT_OFFSET = 0


def _request_id() -> str:
    return "req_" + "".join(secrets.choice(_ALPHANUM) for _ in range(20))


def _meta(pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": clock.now_iso(),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def success_object(data, status_code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status_code


def success_list(items, total_count, limit, offset, status_code=200):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    body = {"meta": _meta(pagination), "response_type": "array", "data": items}
    return jsonify(body), status_code


def error_response(error_id, message, status_code):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status_code
