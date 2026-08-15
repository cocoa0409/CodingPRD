"""Response envelope helpers — SCAFFOLD §1.0 / PRD §2.2.

Success: { "meta": {api_request_id, api_request_timestamp[, pagination]},
           "response_type": "object"|"array", "data": ... }
Error:   { "meta": {api_request_id, api_request_timestamp},
           "response_type": "error", "data": {error_id, message} }
"""
import uuid

from flask import jsonify

from helpers import now_iso


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex,
        "api_request_timestamp": now_iso(),
    }


def ok(data, status=200, pagination=None):
    body = {
        "meta": _meta(),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    if pagination:
        body["meta"].update(pagination)
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp
