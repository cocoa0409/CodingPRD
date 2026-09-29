"""Response envelope helpers (SCAFFOLD section 1.0 / PRD section 2.2)."""

import random
import string
from decimal import Decimal

from flask import jsonify

from db import iso_now

_ALPHABET = string.ascii_lowercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALPHABET) for _ in range(24))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso_now(),
    }
    if extra:
        meta.update(extra)
    return meta


def scrub(value):
    """Make a payload JSON-safe (Decimal -> float)."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [scrub(v) for v in value]
    return value


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": scrub(data if data is not None else {}),
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(items, page):
    body = {
        "meta": _meta(page),
        "response_type": "array",
        "data": scrub(items),
    }
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
