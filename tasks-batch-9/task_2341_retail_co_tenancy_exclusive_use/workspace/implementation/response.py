"""Response envelope helpers (SCAFFOLD response_envelope / PRD 2.2, 2.3)."""
import random
import string
from datetime import datetime, timezone
from decimal import Decimal

from flask import jsonify

from util import fmt_dt

_ALPHABET = string.ascii_lowercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALPHABET) for _ in range(20))


def _plain(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return dict((k, _plain(v)) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_dt(datetime.now(timezone.utc)),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": _plain(data if data is not None else {}),
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def listing(items, limit, offset, total_count):
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + limit) < total_count,
        }),
        "response_type": "array",
        "data": _plain(items),
    }
    return jsonify(body), 200


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
