"""Standard response envelope per PRD section 2.2 / scaffold response_envelope."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=22))


def _meta():
    n = datetime.now(timezone.utc)
    ts = n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"
    return {"api_request_id": _request_id(), "api_request_timestamp": ts}


def success(data, code=200, pagination=None):
    meta = _meta()
    if pagination is not None:
        meta.update(pagination)
    response_type = "array" if isinstance(data, list) else "object"
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), code


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
