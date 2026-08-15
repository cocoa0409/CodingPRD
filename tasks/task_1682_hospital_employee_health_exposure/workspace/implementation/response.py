"""Standard response envelope helpers (PRD section 2.2)."""
import secrets
import string

from flask import jsonify

from db import now
from util import fmt_dt

_ALPHANUM = string.ascii_letters + string.digits


def _meta(pagination=None):
    m = {
        "api_request_id": "req_" + "".join(secrets.choice(_ALPHANUM) for _ in range(22)),
        "api_request_timestamp": fmt_dt(now()),
    }
    if pagination:
        m.update(pagination)
    return m


def success_object(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def success_list(items, pagination):
    return (
        jsonify({"meta": _meta(pagination), "response_type": "array", "data": items}),
        200,
    )


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status
