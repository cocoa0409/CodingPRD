"""Standard response envelope helpers (PRD §2.2, scaffold §1.0)."""

import random
import string

from flask import jsonify

from db import db


def _request_id():
    # PRD §2.2: api_request_id is a server-generated unique identifier that
    # starts with req_.
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(alphabet, k=20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        # PRD §2.2: ISO 8601 UTC timestamp with three fractional digits.
        "api_request_timestamp": db.now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def success(data, status=200, response_type="object"):
    body = {
        "meta": _meta(),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def list_success(items, limit, offset, total_count):
    # PRD §2.3: list responses include limit, offset, total_count, has_more in meta.
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": _meta(
            {
                "limit": limit,
                "offset": offset,
                "total_count": total_count,
                "has_more": has_more,
            }
        ),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status
