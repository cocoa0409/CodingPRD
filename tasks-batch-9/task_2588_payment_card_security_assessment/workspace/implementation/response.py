"""Response envelope helpers (PRD section 2.2 / 2.3)."""

import random
import string

from flask import jsonify

from db import db

_ID_ALPHABET = string.ascii_uppercase + string.digits

# Pagination parameter names and defaults (PRD section 2.3).
LIMIT_PARAM = "limit"
OFFSET_PARAM = "offset"
TOTAL_FIELD = "total_count"
HAS_MORE_FIELD = "has_more"
LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def _request_id():
    return "req_" + "".join(random.choice(_ID_ALPHABET) for _ in range(20))


def build_meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def envelope(data, response_type, http_status=200, meta_extra=None):
    body = {
        "meta": build_meta(meta_extra),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), http_status


def single(data, http_status=200):
    """A single-object success response: meta carries no pagination fields."""
    return envelope(data if data is not None else {}, "object", http_status)


def empty(http_status=200):
    return envelope({}, "object", http_status)


def collection(items, limit, offset, total_count):
    """A list success response: meta carries the four pagination fields."""
    meta_extra = {
        LIMIT_PARAM: limit,
        OFFSET_PARAM: offset,
        TOTAL_FIELD: total_count,
        HAS_MORE_FIELD: (offset + len(items)) < total_count,
    }
    return envelope(items, "array", 200, meta_extra)


def error_body(error_id, message):
    return {
        "meta": build_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
