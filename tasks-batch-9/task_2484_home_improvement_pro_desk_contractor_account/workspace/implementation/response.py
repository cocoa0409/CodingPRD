"""Standard response envelope (PRD 2.2)."""
import random
import string

from flask import jsonify

import clock

_ALPHABET = string.ascii_uppercase + string.digits


def _meta():
    suffix = "".join(random.choice(_ALPHABET) for _ in range(20))
    return {
        "api_request_id": "req_" + suffix,
        "api_request_timestamp": clock.now_iso(),
    }


def obj(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def array(items, status=200, pagination=None):
    meta = _meta()
    if pagination is not None:
        meta.update(pagination)
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
