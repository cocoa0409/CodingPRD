"""Response envelope helpers (PRD section 2.2)."""

import uuid
from decimal import Decimal

from flask import Response
import json

from db import db, iso_ms


def _plain(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:16],
        "api_request_timestamp": iso_ms(db.wall_now()),
    }


def _emit(body, status):
    return Response(
        json.dumps(_plain(body)) + "\n",
        status=status,
        mimetype="application/json",
    )


def object_response(data, status=200):
    return _emit({"meta": _meta(), "response_type": "object", "data": data}, status)


def created_response(data):
    return object_response(data, 201)


def list_response(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return _emit({"meta": meta, "response_type": "array", "data": items}, 200)


def error_response(error_id, message, status):
    return _emit(
        {
            "meta": _meta(),
            "response_type": "error",
            "data": {"error_id": error_id, "message": message},
        },
        status,
    )
