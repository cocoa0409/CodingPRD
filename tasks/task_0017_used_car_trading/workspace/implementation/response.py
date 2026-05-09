"""Response envelope helpers — standard success/error/list envelopes."""

from flask import jsonify

from clock import iso, now
from db import new_request_id


def _meta(extra=None):
    m = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": iso(now()),
    }
    if extra:
        m.update(extra)
    return m


def ok(data, status=200):
    """Single-object success response."""
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def ok_list(items, limit, offset, total_count, status=200):
    body = {
        "meta": _meta(
            {
                "limit": limit,
                "offset": offset,
                "total_count": total_count,
                "has_more": offset + limit < total_count,
            }
        ),
        "response_type": "array",
        "data": items,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error(error_id: str, http_status: int, message: str = ""):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message or error_id,
        },
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp


def replay(event_obj):
    """ERR_IDEMPOTENCY_REPLAY: HTTP 200 + the original event payload + replay marker.

    Per PRD §2.10 the replay returns the original ExternalEvent row with the
    informational replay marker. We surface the original event in `data` and
    include `error_id`/`message` alongside.
    """
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": {
            "error_id": "ERR_IDEMPOTENCY_REPLAY",
            "message": "Duplicate idempotency_key; replayed",
            "event": event_obj,
        },
    }
    resp = jsonify(body)
    resp.status_code = 200
    return resp
