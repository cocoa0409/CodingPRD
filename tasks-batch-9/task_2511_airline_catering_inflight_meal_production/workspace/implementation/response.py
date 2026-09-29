"""Response envelope helpers (PRD 2.2 / 2.3)."""

import random
import string
from datetime import datetime

from flask import jsonify

from timeutil import UTC, fmt_ms

_ALPHABET = string.ascii_lowercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALPHABET) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": fmt_ms(datetime.now(UTC)),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def collection(items, limit, offset, total_count):
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": offset + len(items) < total_count,
        }),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def array(items, status=200):
    """A non-paginated array payload (production plan output)."""
    body = {
        "meta": _meta(),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
