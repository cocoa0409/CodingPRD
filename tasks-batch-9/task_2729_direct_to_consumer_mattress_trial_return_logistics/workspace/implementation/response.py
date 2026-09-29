"""Response envelope helpers."""
import random
import string

from flask import jsonify

from db import db
from util import iso

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso(db.clock),
    }
    if extra:
        meta.update(extra)
    return meta


def single(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def collection(items, limit, offset, total_count):
    page = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + len(items) < total_count,
    }
    body = {"meta": _meta(page), "response_type": "array", "data": items}
    return jsonify(body), 200


def failure(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
