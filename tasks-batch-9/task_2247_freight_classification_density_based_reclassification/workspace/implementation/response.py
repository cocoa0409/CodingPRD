"""Response envelope (PRD 2.2)."""
import random
import string

from flask import jsonify

import clock

_ALPHANUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def base_meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": clock.iso(clock.now()),
    }


def envelope(data, response_type, meta_extra=None):
    meta = base_meta()
    if meta_extra:
        meta.update(meta_extra)
    return {"meta": meta, "response_type": response_type, "data": data}


def ok(data, status=200):
    return jsonify(envelope(data if data is not None else {}, "object")), status


def created(data):
    return ok(data, 201)


def collection(rows, limit, offset, total_count):
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + limit < total_count,
    }
    return jsonify(envelope(rows, "array", meta_extra)), 200


def error(error_id, message, status):
    body = envelope({"error_id": error_id, "message": message}, "error")
    return jsonify(body), status
