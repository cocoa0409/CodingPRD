"""Response envelope helpers (PRD 2.2 / scaffold response_envelope)."""
import random
import string

from flask import jsonify

import store as db

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta(extra=None):
    m = {"api_request_id": _request_id(), "api_request_timestamp": db.wall_iso()}
    if extra:
        m.update(extra)
    return m


def ok(data, code=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data or {}}), code


def created(data):
    return ok(data, 201)


def ok_array(items, pagination=None):
    return (
        jsonify(
            {
                "meta": _meta(pagination),
                "response_type": "array",
                "data": items,
            }
        ),
        200,
    )


def error_response(error_id, message, http_status):
    return (
        jsonify(
            {
                "meta": _meta(),
                "response_type": "error",
                "data": {"error_id": error_id, "message": message},
            }
        ),
        http_status,
    )
