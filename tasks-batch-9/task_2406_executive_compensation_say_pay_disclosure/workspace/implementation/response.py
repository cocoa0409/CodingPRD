"""Response envelope helpers (PRD §2.2, SCAFFOLD response_envelope)."""

import random
import string
from datetime import datetime, timezone
from decimal import Decimal

from flask import jsonify

from db import iso

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _request_timestamp():
    return iso(datetime.now(timezone.utc))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _request_timestamp(),
    }
    if extra:
        meta.update(extra)
    return meta


def scrub(value):
    """Render stored values as JSON-safe primitives."""
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [scrub(v) for v in value]
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, Decimal):
        return float(value)
    return value


def object_response(row, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": scrub(row) if row is not None else {},
    }
    return jsonify(body), status


def list_response(rows, limit, offset, total_count):
    page = scrub(list(rows))
    body = {
        "meta": _meta(
            {
                "limit": limit,
                "offset": offset,
                "total_count": total_count,
                "has_more": offset + len(page) < total_count,
            }
        ),
        "response_type": "array",
        "data": page,
    }
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
