"""Standard response envelope helpers (PRD §2.2, §2.3)."""
import random
import string

from flask import jsonify

from clock import now_iso

ALPHANUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(ALPHANUM) for _ in range(20))


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),
    }
    if extra:
        m.update(extra)
    return m


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        }),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def error(error_id, message, status):
    return jsonify(error_body(error_id, message)), status
