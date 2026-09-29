"""Standard response envelope (PRD 2.2) — meta / response_type / data."""

import random
import string
from datetime import datetime, timezone
from decimal import Decimal

from flask import jsonify

from util import iso_ms

_ALPHANUM = string.ascii_uppercase + string.digits


def api_request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": api_request_id(),
        "api_request_timestamp": iso_ms(datetime.now(timezone.utc)),
    }


def clean(record):
    """Public projection of a stored record: drop private keys, render
    Decimals as JSON numbers."""
    if record is None:
        return None
    out = {}
    for key, value in record.items():
        if key.startswith("_"):
            continue
        if isinstance(value, Decimal):
            out[key] = float(value)
        elif isinstance(value, list):
            out[key] = list(value)
        else:
            out[key] = value
    return out


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": clean(data) if isinstance(data, dict) else (data or {}),
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(rows, limit, offset, total_count, has_more):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = has_more
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [clean(row) for row in rows],
    }
    return jsonify(body), 200


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
