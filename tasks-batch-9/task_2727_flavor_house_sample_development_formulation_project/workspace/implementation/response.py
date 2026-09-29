"""Response envelope helpers (PRD §2.2, scaffold response_envelope)."""

import json
import random
import string
from datetime import datetime, timezone

from flask import Response

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _timestamp():
    d = datetime.now(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        d.year, d.month, d.day, d.hour, d.minute, d.second, d.microsecond // 1000)


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": _timestamp()}


def _emit(payload, status):
    body = json.dumps(payload, allow_nan=False)
    return Response(body, status=status, mimetype="application/json")


def ok(data=None, status=200):
    payload = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return _emit(payload, status)


def created(data):
    return ok(data, 201)


def no_content():
    return Response("", status=204)


def ok_list(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    payload = {"meta": meta, "response_type": "array", "data": rows}
    return _emit(payload, 200)


def ok_array(rows):
    """Array payload for an endpoint that declares no pagination inputs."""
    payload = {"meta": _meta(), "response_type": "array", "data": rows}
    return _emit(payload, 200)


def error(error_id, message, http_status):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return _emit(payload, http_status)
