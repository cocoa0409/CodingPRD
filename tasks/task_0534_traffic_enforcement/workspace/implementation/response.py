import random
import string
from datetime import datetime, timezone

from flask import jsonify

from clock import format_iso_ms


def _request_id():
    aln = string.ascii_letters + string.digits
    return "req_" + "".join(random.choice(aln) for _ in range(20))


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        # request timestamp is wall-clock (real time the response is built),
        # ISO8601 UTC with three fractional digits.
        "api_request_timestamp": format_iso_ms(datetime.now(timezone.utc)),
    }
    if extra:
        m.update(extra)
    return m


def ok_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def ok_array(items, pagination, status=200):
    body = {
        "meta": _meta(pagination),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error_response(error_id, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return body
