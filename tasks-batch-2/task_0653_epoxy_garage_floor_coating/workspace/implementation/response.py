"""Response envelope helpers (SCAFFOLD §1.0 / PRD §2.2)."""
from datetime import datetime, timezone

from flask import jsonify

from db import new_request_id


def _meta(extra=None):
    # api_request_timestamp is a server-generated ISO 8601 UTC timestamp with
    # three fractional digits (PRD §2.2). This is wall-clock server time of the
    # response, NOT the logical clock.
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
    meta = {"api_request_id": new_request_id(), "api_request_timestamp": ts}
    if extra:
        meta.update(extra)
    return meta


def success(data, status=200, pagination=None):
    response_type = "array" if isinstance(data, list) else "object"
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp
