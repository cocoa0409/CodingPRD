"""Standard response envelope helpers (SCAFFOLD.yaml §1.0, PRD §2.2)."""
import secrets
import string
from datetime import datetime, timezone

from flask import jsonify


def _meta():
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
    return {
        "api_request_id": "req_" + "".join(
            secrets.choice(string.ascii_letters + string.digits) for _ in range(20)
        ),
        "api_request_timestamp": ts,
    }


def ok(data, status=200, pagination=None):
    """Success envelope. `pagination` (dict with limit/offset/total_count/has_more)
    marks the response as a list response."""
    meta = _meta()
    if pagination is not None:
        meta.update(pagination)
    response_type = "array" if pagination is not None else "object"
    return jsonify({"meta": meta, "response_type": response_type, "data": data}), status


def err(error_id, message, status):
    return (
        jsonify(
            {
                "meta": _meta(),
                "response_type": "error",
                "data": {"error_id": error_id, "message": message},
            }
        ),
        status,
    )
