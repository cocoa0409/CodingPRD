"""Response envelope helpers (PRD 2.2 / SCAFFOLD response_envelope)."""

import random
import string

from flask import jsonify

from db import iso_instant, wall_now

ALNUM = string.ascii_uppercase + string.digits

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _request_id():
    return "req_" + "".join(random.choice(ALNUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso_instant(wall_now()),
    }
    if extra:
        meta.update(extra)
    return meta


def respond_object(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def respond_array(items, status=200, pagination=None):
    return (
        jsonify({"meta": _meta(pagination), "response_type": "array", "data": items}),
        status,
    )


def respond_error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def paginate(rows, limit, offset):
    total = len(rows)
    window = rows[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(window)) < total,
    }
    return window, pagination
