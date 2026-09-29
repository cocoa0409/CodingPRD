"""Response envelope helpers (PRD section 2.2)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

UTC = timezone.utc
_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _request_timestamp():
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (now.microsecond // 1000)


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _request_timestamp(),
    }
    if extra:
        meta.update(extra)
    return meta


def object_response(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), code


def array_response(items, pagination, code=200):
    body = {"meta": _meta(pagination), "response_type": "array", "data": items}
    return jsonify(body), code


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
