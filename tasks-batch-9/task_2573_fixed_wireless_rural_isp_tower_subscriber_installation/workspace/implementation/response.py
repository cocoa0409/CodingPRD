"""Standard response envelope (PRD 2.2 / 2.3)."""
import json

from flask import Response

import db
from util import format_ts, jsonable, new_request_id


def _meta(extra=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": format_ts(db.now()),
    }
    if extra:
        meta.update(extra)
    return meta


def _emit(payload, status):
    body = json.dumps(jsonable(payload), allow_nan=False)
    return Response(body, status=status, mimetype="application/json")


def object_response(data, status=200):
    return _emit({"meta": _meta(), "response_type": "object", "data": data}, status)


def created(data):
    return object_response(data, 201)


def list_response(items, limit, offset, total_count):
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    })
    return _emit({"meta": meta, "response_type": "array", "data": items}, 200)


def error_response(error_id, message, status):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return _emit(payload, status)
