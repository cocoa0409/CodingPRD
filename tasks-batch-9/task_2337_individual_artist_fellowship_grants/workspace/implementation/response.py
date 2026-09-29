"""Response envelope (PRD section 2.2)."""

import random
import string

from flask import jsonify

import db

_ALPHABET = string.ascii_lowercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALPHABET) for _ in range(16))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.iso3(db.wall_now()),
    }
    if extra:
        meta.update(extra)
    return meta


def obj(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def collection(items, limit, offset, total_count, status=200):
    meta = _meta(
        {
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": offset + len(items) < total_count,
        }
    )
    return jsonify({"meta": meta, "response_type": "array", "data": items}), status


def error(error_id, message, status):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(payload), status
