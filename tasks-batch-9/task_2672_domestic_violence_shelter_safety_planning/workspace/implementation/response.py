"""Standard response envelope helpers (PRD 2.2 / scaffold response_envelope)."""

import random
import string

from flask import jsonify

from db import wall_iso

_ALPHANUM = string.ascii_uppercase + string.digits


def api_request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": api_request_id(),
        "api_request_timestamp": wall_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    """Single-resource (or scalar-object) success envelope."""
    return jsonify({
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }), status


def created(data):
    return ok(data, 201)


def ok_list(items, limit, offset, total_count):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    return jsonify({
        "meta": _meta(pagination),
        "response_type": "array",
        "data": items,
    }), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
