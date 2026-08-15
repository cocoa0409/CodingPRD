"""Standard response envelope helpers.

Envelope shapes come straight from the scaffold `response_envelope`
section and PRD section 2.2:

  success: { "meta": { "api_request_id": "req_...",
                       "api_request_timestamp": "ISO8601" },
             "response_type": "object" | "array",
             "data": {} }
  error:   { "meta": { "api_request_id": ..., "api_request_timestamp": ... },
             "response_type": "error",
             "data": { "error_id": "ERR_XXX", "message": "..." } }

List endpoints add pagination fields (limit, offset, total_count,
has_more) into the meta object.
"""

import secrets
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def _request_timestamp():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def success_object(data, http_status=200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _request_timestamp(),
        },
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), http_status


def success_array(items, limit, offset, total_count, http_status=200):
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _request_timestamp(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), http_status


def error_response(error_id, message, http_status):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _request_timestamp(),
        },
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status
