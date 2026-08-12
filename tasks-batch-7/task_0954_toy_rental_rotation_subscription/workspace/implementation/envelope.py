"""Response envelope helpers matching the scaffold's response_envelope section."""
from flask import jsonify

from timestamps import request_id, request_timestamp


def _meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": request_timestamp(),
    }


def ok_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def ok_list(items, pagination):
    meta = _meta()
    meta.update(pagination)
    body = {"meta": meta, "response_type": "array", "data": items}
    resp = jsonify(body)
    resp.status_code = 200
    return resp


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def error_response(err):
    resp = jsonify(error_body(err.error_id, err.message))
    resp.status_code = err.http_status
    return resp
