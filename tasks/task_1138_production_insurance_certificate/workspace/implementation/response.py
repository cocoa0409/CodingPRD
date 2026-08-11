"""Standard response envelope helpers (PRD section 2.2)."""

import json

from flask import Response

from db import request_id
from util import fmt_dt, now


def _meta(pagination=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": fmt_dt(now()),
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


def success_object(data, status=200):
    payload = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    return _send(payload, status)


def success_list(items, pagination, status=200):
    payload = {
        "meta": _meta(pagination),
        "response_type": "array",
        "data": items,
    }
    return _send(payload, status)


def error_response(error_id, http_status, message):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return _send(payload, http_status)
