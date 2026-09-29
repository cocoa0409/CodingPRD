"""Response envelope helpers -- exactly the structure of PRD section 2.2."""
from flask import jsonify

import store


def _meta(extra=None):
    meta = {
        "api_request_id": store.new_request_id(),
        "api_request_timestamp": store.fmt_instant(store.clock_now()),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def created(data):
    return ok(data, 201)


def listing(records, limit, offset, total_count):
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(records)) < total_count,
    })
    body = {"meta": meta, "response_type": "array", "data": records}
    return jsonify(body), 200


def failure(error_id, message, code):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), code
