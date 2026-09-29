"""Response envelope helpers (PRD 2.2 / 2.3)."""

import random
import string

from flask import jsonify

import clock

_ALPHANUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": clock.iso(clock.now()),
    }
    if extra:
        meta.update(extra)
    return meta


def object_response(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def array_response(rows, limit, offset, total_count):
    has_more = (offset + len(rows)) < total_count
    meta = _meta(
        {
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        }
    )
    return jsonify({"meta": meta, "response_type": "array", "data": rows}), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def no_content():
    return "", 204
