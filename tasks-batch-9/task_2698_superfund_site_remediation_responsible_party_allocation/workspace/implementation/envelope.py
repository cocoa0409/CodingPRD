"""Response envelope (PRD section 2.2, SCAFFOLD response_envelope)."""

import random
import string

from flask import jsonify

import logical_clock

_ALPHANUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": logical_clock.iso(logical_clock.now()),
    }
    if extra:
        meta.update(extra)
    return meta


def obj(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def arr(rows, limit, offset, total_count):
    meta = _meta(
        {
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": offset + len(rows) < total_count,
        }
    )
    return jsonify({"meta": meta, "response_type": "array", "data": rows}), 200


def err(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
