"""Response envelope helpers per PRD 2.2."""
from flask import jsonify
from db import new_request_id, now, fmt_ts


def _meta_base():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": fmt_ts(now()),
    }


def success(data, response_type="object", status=200, pagination=None):
    meta = _meta_base()
    if pagination is not None:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": response_type,
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error(error_id, message, http_status):
    body = {
        "meta": _meta_base(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp
