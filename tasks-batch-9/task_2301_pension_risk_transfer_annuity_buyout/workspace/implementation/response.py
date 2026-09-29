"""Response envelope helpers (PRD 2.2 / 2.3)."""

import random
import string

from flask import jsonify

from db import iso, now

# PRD 2.4 pagination defaults.
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0

_ALPHABET = string.ascii_lowercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALPHABET) for _ in range(20))


def make_meta(extra=None):
    meta = {"api_request_id": request_id(), "api_request_timestamp": iso(now())}
    if extra:
        meta.update(extra)
    return meta


def envelope(data, response_type="object", meta_extra=None):
    return {
        "meta": make_meta(meta_extra),
        "response_type": response_type,
        "data": data,
    }


def object_response(data, status=200):
    return jsonify(envelope(data if data is not None else {}, "object")), status


def list_response(items, limit, offset, total_count, status=200):
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + len(items) < total_count,
    }
    return jsonify(envelope(items, "array", meta_extra)), status


def error_response(error_id, message, status):
    body = envelope({"error_id": error_id, "message": message}, "error")
    return jsonify(body), status
