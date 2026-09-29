"""The response envelope of PRD §2.2 and resource serialisation."""

import json
import random
import string
from decimal import Decimal

from flask import Response

import clock

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": clock.stamp(),
    }
    if extra:
        meta.update(extra)
    return meta


def jsonable(value):
    """Convert stored values into JSON-safe ones, dropping internal keys."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {
            k: jsonable(v) for k, v in value.items() if not k.startswith("_")
        }
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def _send(payload, status):
    body = json.dumps(payload, allow_nan=False)
    return Response(body, status=status, mimetype="application/json")


def object_response(row, status=200):
    return _send(
        {"meta": _meta(), "response_type": "object", "data": jsonable(row)},
        status,
    )


def list_response(page_rows, limit, offset, total_count):
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + len(page_rows) < total_count,
    })
    return _send(
        {"meta": meta, "response_type": "array", "data": jsonable(page_rows)},
        200,
    )


def error_response(error_id, http_status, message):
    return _send(
        {
            "meta": _meta(),
            "response_type": "error",
            "data": {"error_id": error_id, "message": message},
        },
        http_status,
    )
