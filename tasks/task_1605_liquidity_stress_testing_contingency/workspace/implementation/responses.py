"""Standard response envelope helpers (SCAFFOLD response_envelope)."""
import uuid
from datetime import datetime, timezone

from flask import jsonify


def _rid():
    return "req_" + uuid.uuid4().hex[:24]


def _wall_ts():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def ok(data, status=200, response_type="object", pagination=None):
    meta = {"api_request_id": _rid(), "api_request_timestamp": _wall_ts()}
    if pagination is not None:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def ok_list(items, pagination, status=200):
    return ok(items, status=status, response_type="array", pagination=pagination)


def err(error_id, status, message):
    body = {
        "meta": {"api_request_id": _rid(), "api_request_timestamp": _wall_ts()},
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp
