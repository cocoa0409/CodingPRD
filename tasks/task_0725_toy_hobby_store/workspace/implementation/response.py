"""Response envelope helpers."""
import random
import string
from flask import jsonify
from db import now_ts


def _req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(extra=None):
    m = {"api_request_id": _req_id(), "api_request_timestamp": now_ts()}
    if extra:
        m.update(extra)
    return m


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    has_more = offset + len(items) < total_count
    meta = _meta(
        {
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        }
    )
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def err(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
