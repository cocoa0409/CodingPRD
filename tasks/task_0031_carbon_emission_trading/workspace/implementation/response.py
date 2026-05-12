"""Response envelope helpers — matches PRD §2.2 exactly."""

import secrets
import string

from flask import jsonify

import clock


def _request_id():
    alphabet = string.ascii_uppercase + string.ascii_lowercase + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(20))
    return f"req_{suffix}"


def _meta_base():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": clock.iso_format(clock.now()),
    }


def ok(data, status=200):
    body = {
        "meta": _meta_base(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def created(data):
    return ok(data, status=201)


def list_ok(items, *, limit, offset, total_count, status=200):
    meta = _meta_base()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + limit) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error(error_id, http_status, message):
    body = {
        "meta": _meta_base(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status
