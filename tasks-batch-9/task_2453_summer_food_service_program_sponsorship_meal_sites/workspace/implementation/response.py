"""Response envelope helpers (PRD sec 2.2 / sec 2.3)."""

import random
import string

from flask import jsonify

import db

_ALPHANUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.clock.now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created_response(data):
    return object_response(data, 201)


def list_response(items, limit, offset, total_count):
    meta = _meta(
        {
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        }
    )
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def paginate(rows, limit, offset, serializer):
    """Apply the default created_at ascending ordering, then the page window."""
    ordered_rows = db.ordered(rows)
    total = len(ordered_rows)
    page = ordered_rows[offset : offset + limit]
    return list_response([serializer(row) for row in page], limit, offset, total)
