"""Standard response envelope (PRD 2.2 / scaffold response_envelope)."""
import random
import string

from flask import jsonify

from db import now_iso

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def build_meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    return jsonify({
        "meta": build_meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }), status


def created(data):
    return ok(data, 201)


def ok_list(items, page_meta):
    return jsonify({
        "meta": build_meta(page_meta),
        "response_type": "array",
        "data": items,
    }), 200


def error(error_id, message, status):
    return jsonify({
        "meta": build_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }), status
