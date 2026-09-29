"""Response envelope helpers (SCAFFOLD 1.0 / PRD 2.2, 2.3)."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify

_ALPHABET = string.ascii_lowercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALPHABET) for _ in range(24))


def _timestamp():
    dt = datetime.now(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def _meta(extra=None):
    meta = {"api_request_id": request_id(), "api_request_timestamp": _timestamp()}
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def created(data):
    return ok(data, 201)


def ok_list(items, limit, offset, total_count):
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    })
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
