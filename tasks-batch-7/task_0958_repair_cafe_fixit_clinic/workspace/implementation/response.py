"""Standard response envelope helpers (scaffold §1.0 / PRD §2.2)."""

import json
import uuid

from flask import Response

from db import wall_now_iso


def _request_id():
    return "req_" + uuid.uuid4().hex


def _meta(pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": wall_now_iso(),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def success(data, code=200, response_type="object", pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    return Response(json.dumps(body), status=code, mimetype="application/json")


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return Response(json.dumps(body), status=status, mimetype="application/json")
