"""Response envelope helpers — exact structure from SCAFFOLD response_envelope."""
import uuid

from flask import jsonify

from db import STORE
from util import fmt_dt


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex,
        "api_request_timestamp": fmt_dt(STORE.clock),
    }


def ok(data, code=200, response_type="object", pagination=None):
    body = {"meta": _meta(), "response_type": response_type, "data": data}
    if pagination is not None:
        body["meta"].update(pagination)
    resp = jsonify(body)
    resp.status_code = code
    return resp


def ok_list(items, pagination):
    return ok(items, 200, "array", pagination)


def err(error_id, status, message=None):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message or error_id},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp
