"""Response envelope per SCAFFOLD response_envelope / PRD §2.2."""
from flask import jsonify

from db import request_id, now_iso


def _meta(pagination=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": now_iso(),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def success(data, status=200, response_type="object", pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def success_list(items, pagination):
    return success(items, status=200, response_type="array", pagination=pagination)


def error(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": err.error_id,
            "message": err.message,
        },
    }
    return jsonify(body), err.http_status
