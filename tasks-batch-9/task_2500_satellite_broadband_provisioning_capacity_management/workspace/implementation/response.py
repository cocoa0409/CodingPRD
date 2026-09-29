"""The standard response envelope (PRD 2.2)."""

import json
import random
import string

from flask import Response

from clock import clock, fmt

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt(clock.now()),
    }


def _dump(payload):
    return json.dumps(payload, default=str)


def _respond(payload, status):
    return Response(_dump(payload), status=status, mimetype="application/json")


def object_response(data, status=200):
    payload = {
        "meta": _base_meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return _respond(payload, status)


def list_response(items, limit, offset, total_count, status=200):
    meta = _base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    payload = {"meta": meta, "response_type": "array", "data": items}
    return _respond(payload, status)


def error_response(error_id, message, status):
    payload = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return _respond(payload, status)
