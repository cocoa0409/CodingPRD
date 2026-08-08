"""Response envelope helpers and entity serialization."""

import random
import string
from datetime import datetime

from flask import jsonify

import store


def gen_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(extra=None):
    m = {
        "api_request_id": gen_request_id(),
        "api_request_timestamp": store.render_dt(store.now()),
    }
    if extra:
        m.update(extra)
    return m


def serialize(entity):
    """Return a JSON-safe copy: strip internal keys, render datetimes."""
    out = {}
    for k, v in entity.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = store.render_dt(v)
        else:
            out[k] = v
    return out


def success(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": serialize(data) if isinstance(data, dict) else data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def created(data):
    return success(data, status=201)


def empty_success(status=200):
    body = {"meta": _meta(), "response_type": "object", "data": {}}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def listing(items, limit, offset, total):
    has_more = (offset + limit) < total
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": has_more,
        }),
        "response_type": "array",
        "data": [serialize(i) for i in items],
    }
    resp = jsonify(body)
    resp.status_code = 200
    return resp


def error_response(error_id, message):
    from errors import ERROR_STATUS
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = ERROR_STATUS.get(error_id, 400)
    return resp
