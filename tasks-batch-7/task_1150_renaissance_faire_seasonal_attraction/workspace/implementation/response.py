"""Response envelope helpers per PRD section 2.2 / 2.3."""
import json

from flask import Response

from util import new_request_id, now_str, jsonable


def _meta(pagination=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": now_str(),
    }
    if pagination:
        meta.update(pagination)
    return meta


def _send(payload, status):
    return Response(
        json.dumps(payload),
        status=status,
        mimetype="application/json",
    )


def obj_response(data, status=200):
    payload = {
        "meta": _meta(),
        "response_type": "object",
        "data": jsonable(data),
    }
    return _send(payload, status)


def list_response(items, limit, offset, total_count):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + len(items) < total_count,
    }
    payload = {
        "meta": _meta(pagination),
        "response_type": "array",
        "data": jsonable(items),
    }
    return _send(payload, 200)


def error_response(error_id, status, message):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return _send(payload, status)
