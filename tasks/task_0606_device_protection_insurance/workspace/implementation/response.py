"""Response envelope helpers."""
import random
import string

from flask import jsonify

from clock import iso_now_real


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(extra=None):
    m = {"api_request_id": _request_id(), "api_request_timestamp": iso_now_real()}
    if extra:
        m.update(extra)
    return m


def ok(data, status=200, response_type="object"):
    body = {"meta": _meta(), "response_type": response_type, "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    body = {
        "meta": _meta(meta_extra),
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
