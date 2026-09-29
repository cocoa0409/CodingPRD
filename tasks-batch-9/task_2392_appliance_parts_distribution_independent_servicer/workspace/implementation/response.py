"""Response envelope helpers (PRD 2.2 / scaffold response_envelope)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

_ALPHABET = string.ascii_lowercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALPHABET) for _ in range(24))


def _wall_stamp():
    dt = datetime.now(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _wall_stamp(),
    }


def ok(data=None, status=200):
    body = {
        "meta": meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(items, limit, offset, total_count):
    m = meta()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total_count
    m["has_more"] = (offset + len(items)) < total_count
    body = {
        "meta": m,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error(error_id, message, http_status):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
