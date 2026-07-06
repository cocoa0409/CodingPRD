import random
import string

from flask import jsonify

from clock import iso_millis
from db import db

# Fields that are internal-only and must never be serialized in responses.
_HIDDEN = ("_seq", "_created_dt")


def _request_id():
    alnum = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(alnum, k=20))


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso_millis(db.now()),
    }
    if extra:
        m.update(extra)
    return m


def public(entity):
    """Return a copy of an entity with internal fields stripped."""
    return {k: v for k, v in entity.items() if k not in _HIDDEN}


def ok_object(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": public(data) if data is not None else {},
    }
    return jsonify(body), status


def ok_array(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        }),
        "response_type": "array",
        "data": [public(i) for i in items],
    }
    return jsonify(body), 200


def ok_raw(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
