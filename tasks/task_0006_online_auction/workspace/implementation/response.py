import secrets
import string
from flask import jsonify

from db import fmt_dt, now


def _request_id() -> str:
    alphabet = string.ascii_uppercase + string.digits
    body = "".join(secrets.choice(alphabet) for _ in range(20))
    return f"req_{body}"


def _meta() -> dict:
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_dt(now()),
    }


def success(data, http_status=200, response_type=None, pagination: dict = None):
    if response_type is None:
        response_type = "array" if isinstance(data, list) else "object"
    meta = _meta()
    if pagination:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    resp = jsonify(body)
    resp.status_code = http_status
    return resp


def error(error_id: str, message: str, http_status: int):
    meta = _meta()
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp
