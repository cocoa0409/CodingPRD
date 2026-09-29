"""Standard response envelope (PRD 2.2) and serialisation helpers."""

import random
import string
from datetime import datetime
from decimal import Decimal

from flask import jsonify

from db import iso, real_now_iso

_ALPHANUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": real_now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def serialise(row):
    """Public projection of a stored row: strip private keys, normalise types."""
    if row is None:
        return None
    out = {}
    for key, value in row.items():
        if key.startswith("_"):
            continue
        out[key] = _value(value)
    return out


def _value(value):
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list):
        return [_value(item) for item in value]
    if isinstance(value, dict):
        return {k: _value(v) for k, v in value.items()}
    return value


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": serialise(data) if isinstance(data, dict) else (data or {}),
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(rows, pagination):
    body = {
        "meta": _meta(pagination),
        "response_type": "array",
        "data": [serialise(row) for row in rows],
    }
    return jsonify(body), 200


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
