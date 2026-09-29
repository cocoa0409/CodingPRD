"""Response envelope (PRD 2.2 / 2.3)."""

import random
import string

from flask import jsonify

import clock

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def build_meta(extra=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": clock.iso_now(),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    body = {
        "meta": build_meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def ok_list(rows, limit, offset, total_count):
    has_more = (offset + len(rows)) < total_count
    body = {
        "meta": build_meta(
            {
                "limit": limit,
                "offset": offset,
                "total_count": total_count,
                "has_more": has_more,
            }
        ),
        "response_type": "array",
        "data": rows,
    }
    return jsonify(body), 200


def error(error_id, message, status):
    body = {
        "meta": build_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
