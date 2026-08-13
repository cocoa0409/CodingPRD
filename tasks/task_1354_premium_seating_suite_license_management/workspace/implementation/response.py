"""Standard response envelope helpers per SCAFFOLD table 1.0 / PRD section 2.2."""
import secrets
import string
from flask import jsonify

import db
from util import fmt_ts


def _request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def _meta(pagination=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_ts(db.clock()),
    }
    if pagination is not None:
        m.update(pagination)
    return m


def success(data, status=200, response_type="object", pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def success_list(items, pagination):
    return success(items, status=200, response_type="array", pagination=pagination)


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status
