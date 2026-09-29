"""Response envelope helpers."""

import random
import string
from datetime import datetime

from flask import jsonify

import clock

_ALPHABET = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALPHABET) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": clock.format_iso(clock.now()),
    }
    if extra:
        meta.update(extra)
    return meta


_THREE_DIGIT_FIELDS = ("created_at", "updated_at")


def serialize(row):
    """Public projection of a stored row: strip internals, format datetimes."""
    if row is None:
        return None
    out = {}
    for key, value in row.items():
        if key.startswith("_"):
            continue
        if isinstance(value, datetime):
            if key in _THREE_DIGIT_FIELDS:
                out[key] = clock.format_iso(value)
            else:
                out[key] = clock.format_iso_instant(value)
        elif isinstance(value, list):
            out[key] = list(value)
        else:
            out[key] = value
    return out


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def collection(rows, page_meta):
    body = {
        "meta": _meta(page_meta),
        "response_type": "array",
        "data": rows,
    }
    return jsonify(body), 200


def error(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
