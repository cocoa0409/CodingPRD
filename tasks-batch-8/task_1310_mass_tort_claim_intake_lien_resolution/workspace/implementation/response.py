"""Response envelope helpers per PRD section 2.2."""

import uuid
from datetime import datetime, timezone

from flask import jsonify


def _make_meta(extra=None):
    meta = {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S."
        )
        + "%03dZ" % (datetime.now(timezone.utc).microsecond // 1000),
    }
    if extra:
        meta.update(extra)
    return meta


def success_envelope(data, status_code=200, response_type="object", pagination=None):
    """Build a success response envelope.

    Args:
        data: the resource dict or list of dicts.
        status_code: HTTP status code.
        response_type: "object" or "array".
        pagination: dict with keys limit, offset, total_count, has_more (for list endpoints).
    """
    meta_extra = pagination if pagination else None
    body = {
        "meta": _make_meta(meta_extra),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status_code


def error_envelope(error_id, message, http_status):
    """Build an error response envelope."""
    body = {
        "meta": _make_meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status
