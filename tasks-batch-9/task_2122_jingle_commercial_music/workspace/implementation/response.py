"""Standard response envelope (PRD 2.2)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

_ALNUM = string.ascii_uppercase + string.digits


def _api_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _api_request_timestamp():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def _meta(extra=None):
    meta = {
        "api_request_id": _api_request_id(),
        "api_request_timestamp": _api_request_timestamp(),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data or {}}), status


def created(data):
    return ok(data, 201)


def ok_list(items, pagination):
    return jsonify({"meta": _meta(pagination), "response_type": "array", "data": items}), 200


def error(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status
