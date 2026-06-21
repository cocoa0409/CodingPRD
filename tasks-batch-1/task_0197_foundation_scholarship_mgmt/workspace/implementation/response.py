"""Standard response envelope helpers (PRD §2.2)."""

import random
import string

from flask import jsonify

import db


def _request_id():
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


# Internal-only fields that must never appear in serialized output.
_HIDDEN = {"_seq"}


def _public(record):
    if isinstance(record, dict):
        return {k: v for k, v in record.items() if k not in _HIDDEN}
    return record


def ok(data, status=200, response_type="object", pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": _public(data),
    }
    return jsonify(body), status


def ok_object(data, status=200):
    return ok(data, status=status, response_type="object")


def ok_array(items, pagination):
    body = {
        "meta": _meta(pagination),
        "response_type": "array",
        "data": [_public(i) for i in items],
    }
    return jsonify(body), 200


def error(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
