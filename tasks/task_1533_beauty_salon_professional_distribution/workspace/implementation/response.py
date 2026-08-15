"""Response envelope helpers matching the scaffold's response_envelope."""

import random
import string
from flask import jsonify

import db as dbmod


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": dbmod.now_iso(),
    }
    if extra:
        m.update(extra)
    return m


def success_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def success_list(items, limit, offset, total_count, status=200):
    has_more = (offset + len(items)) < total_count
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    })
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def no_content():
    return "", 204


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
