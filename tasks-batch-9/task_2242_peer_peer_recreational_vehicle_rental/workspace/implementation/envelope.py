"""Response envelope helpers (PRD 2.2)."""

import random
import string

from flask import jsonify

from store import now_iso

_ALPHANUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def object_response(data, status=200):
    return jsonify({
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }), status


def list_response(items, limit, offset, total_count):
    return jsonify({
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": offset + len(items) < total_count,
        }),
        "response_type": "array",
        "data": items,
    }), 200


def error_response(error_id, message, status):
    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }), status
