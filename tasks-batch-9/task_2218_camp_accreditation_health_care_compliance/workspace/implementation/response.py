"""Standard response envelope (PRD 2.2)."""

import random
import string

from flask import jsonify

import clock

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def meta(extra=None):
    m = {
        "api_request_id": request_id(),
        "api_request_timestamp": clock.now_iso(),
    }
    if extra:
        m.update(extra)
    return m


def ok(data, status=200):
    body = {"meta": meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def listing(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": meta(
            {
                "limit": limit,
                "offset": offset,
                "total_count": total_count,
                "has_more": has_more,
            }
        ),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def failure(error_id, message, status):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset: offset + limit], total
