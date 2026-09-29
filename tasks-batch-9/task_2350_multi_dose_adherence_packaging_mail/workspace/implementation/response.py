"""Response envelope helpers (PRD 2.2)."""

import random
import string

from flask import jsonify

import clock

_ALPHANUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _meta(pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": clock.wall_iso(),
    }
    if pagination:
        meta.update(pagination)
    return meta


def object_response(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def array_response(items, pagination=None, status=200):
    return (
        jsonify({"meta": _meta(pagination), "response_type": "array", "data": items}),
        status,
    )


def error_response(error_id, message, status):
    return (
        jsonify(
            {
                "meta": _meta(),
                "response_type": "error",
                "data": {"error_id": error_id, "message": message},
            }
        ),
        status,
    )
