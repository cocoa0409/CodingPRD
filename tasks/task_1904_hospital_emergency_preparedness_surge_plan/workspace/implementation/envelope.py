"""Response envelope helpers, per SCAFFOLD response_envelope / PRD §2.2."""

from flask import jsonify

from db import clock
from util import fmt_dt, new_request_id


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": fmt_dt(clock.now()),
    }


def success(data, response_type="object", status=200, pagination=None):
    body = {
        "meta": _meta(),
        "response_type": response_type,
        "data": data,
    }
    if pagination is not None:
        body["meta"].update(pagination)
    return jsonify(body), status


def error_envelope(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
