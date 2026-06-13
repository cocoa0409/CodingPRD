"""Standard response envelope (PRD §2.2, SCAFFOLD §1.0)."""
from flask import jsonify

from util import iso_now, request_id


def _meta(extra=None):
    m = {
        "api_request_id": request_id(),
        "api_request_timestamp": iso_now(),
    }
    if extra:
        m.update(extra)
    return m


def success(data, status=200, pagination=None):
    """Object/array success envelope.

    response_type is "array" when data is a list, otherwise "object".
    Pagination fields (limit/offset/total_count/has_more) live inside meta.
    """
    response_type = "array" if isinstance(data, list) else "object"
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp
