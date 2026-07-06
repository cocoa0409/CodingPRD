import random
import string

from flask import jsonify

from db import db

# Any field whose name starts with "_" is internal and never serialized.


def _request_id():
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.clock.now_iso(),
    }
    if extra:
        m.update(extra)
    return m


def public(entity):
    if entity is None:
        return None
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": public(data) if isinstance(data, dict) else (data if data is not None else {}),
    }
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
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


def error_body(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
