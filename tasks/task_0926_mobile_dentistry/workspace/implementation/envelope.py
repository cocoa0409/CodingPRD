"""Response envelope helpers (PRD 2.2)."""

import random
import string

from flask import jsonify, g

import clock
from timefmt import render_instant

_ALPHANUM = string.ascii_uppercase + string.digits


def _request_id():
    existing = getattr(g, "api_request_id", None)
    if existing:
        return existing
    generated = "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))
    g.api_request_id = generated
    return generated


def _meta():
    return {
        "api_request_id": _request_id(),
        # The response envelope's timestamp is rendered by the very same
        # canonical instant renderer as every domain instant.
        "api_request_timestamp": render_instant(clock.now()),
    }


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def array_response(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
